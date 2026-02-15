from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from .db import get_conn

from .config import settings
from .search import hybrid_search, ChunkHit
from .agentic_research import decide_web_and_contexts
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
        ctx_blob = "\n\n".join(contexts)[:15000]
        conversation_block = f"Conversation so far (truncated):\n{cc}\n\n" if cc else ""
        prompt = (
            "Please refine and improve the following draft answer using the provided context and conversation so far.\n\n"
            f"Question: {question}\n\n"
            f"{conversation_block}"
            f"Draft Answer:\n{draft}\n\nContext:\n{ctx_blob}\n\n"
            "Return a concise, well-structured answer grounded in the context and consistent with the conversation."
        )
        return llm_chat(prompt, "", provider_override=provider_override, max_tokens=900, temperature=0.2)
    except Exception:
        return None


def ask(user_id: int, space_id: Optional[int], conversation_id: str, message: str, provider_override: Optional[str] = None, force_web: bool = False) -> Dict[str, object]:
    start_ts = time.monotonic()
    max_budget = max(float(settings.deep_research_timeout_seconds or 0), 15.0)

    def _remaining_budget() -> float:
        elapsed = time.monotonic() - start_ts
        remaining = max_budget - elapsed
        return max(0.0, remaining)

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
    local_top_k = max(15, int(settings.deep_research_local_top_k or 15))
    for sq in subqs:
        try:
            hits = hybrid_search(sq, top_k=local_top_k, user_id=user_id, space_id=space_id)
            hits_all.extend(hits)
            if hits:
                contexts.append("\n\n".join(h.content for h in hits))
        except Exception as e:
            logger.warning("DR retrieve failed for %r: %s", sq, e)

    # If no hits at all, answer from zero context
    if not contexts:
        contexts.append("(No relevant context found in your knowledge base.)")

    contexts, web_hits, confidence, web_attempted = decide_web_and_contexts(
        message,
        hits_all,
        contexts,
        max_seconds=_remaining_budget(),
        web_top_k=max(15, int(settings.deep_research_web_top_k or 15)),
        force_web=force_web,
    )

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
    local_hits = hits_all[:min(len(hits_all), max(5, int(settings.deep_research_local_top_k or 15)))]
    doc_meta: Dict[int, Dict[str, object]] = {}
    if local_hits:
        doc_ids = sorted({int(h.document_id) for h in local_hits})
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, COALESCE(title,''), source_path FROM documents WHERE id = ANY(%s)",
                    (doc_ids,),
                )
                for row in cur.fetchall():
                    doc_meta[int(row[0])] = {
                        "title": row[1] or "",
                        "source_path": row[2] or "",
                    }
    try:
        for idx, h in enumerate(local_hits, start=1):
            info = doc_meta.get(int(h.document_id), {})
            refs.append({
                "document_id": h.document_id,
                "chunk_id": h.chunk_id,
                "chunk_index": h.chunk_index,
                "source": "local",
                "title": info.get("title") or "",
                "source_path": info.get("source_path") or "",
                "excerpt": h.content,
                "rank": idx,
            })
        web_limit = max(5, int(settings.deep_research_web_top_k or 15))
        for idx, hit in enumerate(web_hits[:web_limit], start=1):
            refs.append({
                "source": "web",
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
                "rank": idx,
            })
    except Exception:
        pass

    return {
        "conversation_id": conversation_id,
        "answer": answer,
        "message_count": len(st.messages),
        "references": refs,
        "confidence": confidence,
        "web_attempted": web_attempted,
        "elapsed_seconds": round(time.monotonic() - start_ts, 2),
    }