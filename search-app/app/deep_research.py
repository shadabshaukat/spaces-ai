from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from .config import settings
from .search import hybrid_search, ChunkHit
from .valkey_cache import get_json as cache_get, set_json as cache_set

logger = logging.getLogger(__name__)

# Fallback in-process memory if Valkey is not configured/available
_MEM: Dict[str, Dict[str, object]] = {}


@dataclass
class Message:
    role: str  # 'user' | 'assistant' | 'system'
    content: str


@dataclass
class DRState:
    user_id: int
    space_id: Optional[int]
    conversation_id: str
    messages: List[Message] = field(default_factory=list)

    def key(self) -> str:
        # Namespaced per user + space to avoid any cross-user leakage
        sid = self.space_id if self.space_id is not None else "_"
        return f"dr:{self.user_id}:{sid}:{self.conversation_id}"

    def trim(self, keep: int = 20) -> None:
        # Keep the last N dialogue turns (pairs) or last N messages; simple heuristic: last 2*keep messages
        max_msgs = max(int(keep) * 2, 40)
        if len(self.messages) > max_msgs:
            self.messages = self.messages[-max_msgs:]


def _load_state(user_id: int, space_id: Optional[int], conversation_id: str) -> DRState:
    key_prefix = f"dr:{user_id}:{space_id if space_id is not None else '_'}:{conversation_id}"
    data = cache_get(key_prefix) or _MEM.get(key_prefix)
    if data and isinstance(data, dict):
        msgs = [Message(**m) for m in data.get("messages", [])]
        return DRState(user_id=user_id, space_id=space_id, conversation_id=conversation_id, messages=msgs)
    return DRState(user_id=user_id, space_id=space_id, conversation_id=conversation_id, messages=[])


def _save_state(state: DRState) -> None:
    # Persist small JSON blob to Valkey with default TTL rollover; also mirror in-process fallback
    payload = {"messages": [m.__dict__ for m in state.messages]}
    try:
        cache_set(state.key(), payload, ttl_seconds=settings.session_max_age_seconds)
    except Exception:
        pass
    _MEM[state.key()] = payload


def start_conversation(user_id: int, space_id: Optional[int]) -> str:
    cid = uuid.uuid4().hex[:12]
    st = DRState(user_id=user_id, space_id=space_id, conversation_id=cid, messages=[
        Message("system", "You are Deep Research mode for SpacesAI. You work step-by-step: plan, retrieve, analyze, synthesize. Always ground answers in the user's knowledge base for this space. If something isn't in the KB, clearly say so.")
    ])
    _save_state(st)
    logger.info("DR start: user=%s space=%s cid=%s", user_id, space_id, cid)
    return cid


def _extract_subqueries(question: str) -> List[str]:
    # Heuristic split into 2-4 sub-questions using simple rules
    q = question.strip()
    if len(q) < 80:
        return [q]
    # Split by 'and', 'or', commas where it makes sense
    parts = re.split(r"\b(?:and|or|,|;|\n)\b", q, flags=re.IGNORECASE)
    subs = [p.strip() for p in parts if p.strip()]
    if 1 < len(subs) <= 6:
        return subs[:4]
    return [q]


def _synthesize(question: str, contexts: List[str], provider_override: Optional[str], conv_context: Optional[str] = None) -> Optional[str]:
    try:
        from .llm import chat as llm_chat
        aggregated = "\n\n".join(contexts)[:16000]
        cc = (conv_context or "").strip()
        # Prepend recent conversation context to retrieval context so LLM continues the same topic
        full_ctx = (("Conversation so far:\n" + cc + "\n\n") if cc else "") + aggregated
        return llm_chat(
            question,
            full_ctx,
            provider_override=provider_override,
            max_tokens=800,
            temperature=0.2,
        )
    except Exception as e:
        logger.exception("DR synth failed: %s", e)
        return None


def _refine(question: str, draft: str, contexts: List[str], provider_override: Optional[str], conv_context: Optional[str] = None) -> Optional[str]:
    try:
        from .llm import chat as llm_chat
        cc = (conv_context or "").strip()[:1200]
        prompt = (
            f"Please refine and improve the following draft answer using the provided context and conversation so far.\n\n"
            f"Question: {question}\n\n"
            + (f"Conversation so far (truncated):\n{cc}\n\n" if cc else "")+
            f"Draft Answer:\n{draft}\n\nContext:\n{('\n\n'.join(contexts))[:15000]}\n\n"
            "Return a concise, well-structured answer grounded in the context and consistent with the conversation."
        )
        return llm_chat(prompt, "", provider_override=provider_override, max_tokens=900, temperature=0.2)
    except Exception:
        return None


def ask(user_id: int, space_id: Optional[int], conversation_id: str, message: str, provider_override: Optional[str] = None) -> Dict[str, object]:
    # Load state
    st = _load_state(user_id, space_id, conversation_id)
    st.messages.append(Message("user", message))

    # Build recent conversation snippet to keep topic continuity in retrieval and synthesis
    recent = "\n".join(m.content for m in st.messages[-8:] if m.role in ("user", "assistant"))
    recent_snippet = recent[-1000:] if recent else ""

    # PLAN (use current message + recent context to disambiguate short follow-ups)
    retrieval_seed = f"{message}\n\nConversation so far:\n{recent_snippet}" if recent_snippet else message
    subqs = _extract_subqueries(retrieval_seed)

    # RETRIEVE for each subq
    contexts: List[str] = []
    hits_all: List[ChunkHit] = []
    for sq in subqs:
        try:
            hits = hybrid_search(sq, top_k=12, user_id=user_id, space_id=space_id)
            hits_all.extend(hits)
            if hits:
                contexts.append("\n\n".join(h.content for h in hits))
        except Exception as e:
            logger.warning("DR retrieve failed for %r: %s", sq, e)

    # If no hits at all, answer from zero context
    if not contexts:
        contexts.append("(No relevant context found in your knowledge base.)")

    # SYNTHESIZE
    draft = _synthesize(message, contexts, provider_override, conv_context=recent_snippet)
    answer = draft or "".join(contexts)[:1200]

    # LIGHT REFINE
    if draft and len(hits_all) > 0:
        refined = _refine(message, draft, contexts[:3], provider_override, conv_context=recent_snippet)
        if refined:
            answer = refined

    st.messages.append(Message("assistant", answer))
    st.trim(keep=20)
    _save_state(st)

    # Prepare references (top few)
    refs: List[Dict[str, object]] = []
    try:
        # Map to the top first 5 chunks for quick refs
        for h in hits_all[:5]:
            refs.append({
                "document_id": h.document_id,
                "chunk_id": h.chunk_id,
                "chunk_index": h.chunk_index,
            })
    except Exception:
        pass

    return {
        "conversation_id": conversation_id,
        "answer": answer,
        "message_count": len(st.messages),
        "references": refs,
    }