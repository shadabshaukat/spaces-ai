from __future__ import annotations

import logging
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)


def chat(question: str, context: str, provider_override: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.2) -> Optional[str]:
    provider = (provider_override or settings.llm_provider or "none").lower()

    if provider == "oci":
        try:
            # Reuse existing OCI logic
            from .oci_llm import oci_chat_completion
            return oci_chat_completion(question, context, max_tokens=max_tokens, temperature=temperature)
        except Exception as e:
            logger.exception("OCI LLM failed: %s", e)
            return None

    if provider == "openai":
        try:
            from openai import OpenAI  # type: ignore
            if not settings.openai_api_key:
                return None
            client = OpenAI(api_key=settings.openai_api_key)
            prompt = (
                "You are a helpful assistant. Using the provided context, answer the question concisely.\n\n"
                f"Question: {question}\n\nContext:\n{context[:12000]}"
            )
            resp = client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.exception("OpenAI LLM failed: %s", e)
            return None

    if provider == "bedrock":
        # AWS Bedrock (text generation/chat abstraction)
        try:
            import boto3  # type: ignore
            import json
            model_id = (getattr(settings, "aws_bedrock_model_id", None) or "").strip() or "anthropic.claude-3-sonnet-20240229-v1:0"
            region = getattr(settings, "aws_region", None) or "us-east-1"
            runtime = boto3.client("bedrock-runtime", region_name=region)
            # Use Messages API schema for Anthropic models
            messages = [
                {"role": "user", "content": [{"type": "text", "text": f"Question: {question}\n\nContext:\n{context[:12000]}"}]}
            ]
            req = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            body = json.dumps(req)
            resp = runtime.invoke_model(modelId=model_id, body=body)
            out = json.loads(resp["body"].read().decode("utf-8"))
            # Extract as concatenated text blocks
            try:
                parts = out.get("output", {}).get("message", {}).get("content", [])
                txt = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
                return txt or None
            except Exception:
                return out.get("content") or out.get("outputText") or None
        except Exception as e:
            logger.exception("Bedrock LLM failed: %s", e)
            return None

    if provider == "ollama":
        # Local Ollama server (http://localhost:11434)
        try:
            import requests  # type: ignore
            host = getattr(settings, "ollama_host", None) or "http://localhost:11434"
            model = getattr(settings, "ollama_model", None) or "llama3.2:latest"
            prompt = (
                "You are a helpful assistant. Using only the provided context, answer concisely.\n\n"
                f"Question: {question}\n\nContext:\n{context[:12000]}"
            )
            payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": temperature}}
            logger.info("llm[ollama]: generate (model=%s)", model)
            r = requests.post(f"{host}/api/generate", json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            out = data.get("response") or data.get("output")
            logger.info("llm[ollama]: got answer=%s", bool(out))
            return out
        except Exception as e:
            logger.exception("Ollama LLM failed: %s", e)
            return None


    return None
