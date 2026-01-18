from __future__ import annotations

import base64
import hmac
import json
import logging
from hashlib import sha256
from typing import Optional

from fastapi import Request

from .config import settings

logger = logging.getLogger(__name__)


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = '=' * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_session(payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(settings.secret_key.encode("utf-8"), data, sha256).digest()
    return _b64e(data) + "." + _b64e(sig)


def verify_session(token: str) -> Optional[dict]:
    try:
        data_b64, sig_b64 = token.split(".", 1)
        data = _b64d(data_b64)
        sig = _b64d(sig_b64)
        expected = hmac.new(settings.secret_key.encode("utf-8"), data, sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        obj = json.loads(data.decode("utf-8"))
        if not isinstance(obj, dict):
            return None
        # minimal validation
        if "user_id" not in obj or "email" not in obj:
            return None
        return obj
    except Exception:
        return None


async def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    u = verify_session(token)
    return u


def set_session_cookie_headers(token: str) -> dict[str, str]:
    attrs = [
        f"{settings.session_cookie_name}={token}",
        "Path=/",
        f"Max-Age={settings.session_max_age_seconds}",
        "HttpOnly",
    ]
    samesite = (settings.cookie_samesite or "Lax")
    attrs.append(f"SameSite={samesite}")
    if settings.cookie_secure:
        attrs.append("Secure")
    return {"Set-Cookie": "; ".join(attrs)}


def clear_session_cookie_headers() -> dict[str, str]:
    attrs = [
        f"{settings.session_cookie_name}=null",
        "Path=/",
        "Max-Age=0",
        "HttpOnly",
    ]
    samesite = (settings.cookie_samesite or "Lax")
    attrs.append(f"SameSite={samesite}")
    if settings.cookie_secure:
        attrs.append("Secure")
    return {"Set-Cookie": "; ".join(attrs)}
