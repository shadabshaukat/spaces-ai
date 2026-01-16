from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis  # type: ignore

from .config import settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def _get_client() -> Optional[redis.Redis]:
    global _client
    if _client is not None:
        return _client
    if not settings.valkey_host:
        return None
    try:
        kwargs: dict[str, Any] = {
            "host": settings.valkey_host,
            "port": settings.valkey_port,
            "db": settings.valkey_db,
            "socket_timeout": 2.0,
            "socket_connect_timeout": 2.0,
            "retry_on_timeout": True,
            "decode_responses": True,
        }
        if settings.valkey_password:
            kwargs["password"] = settings.valkey_password
        if settings.valkey_tls:
            kwargs["ssl"] = True
        _client = redis.Redis(**kwargs)
        # Probe connection lightly
        try:
            _client.ping()
        except Exception:
            logger.warning("Valkey ping failed; caching disabled")
            return None
        return _client
    except Exception as e:
        logger.warning("Valkey init failed: %s", e)
        return None


def get_json(key: str) -> Optional[Any]:
    cli = _get_client()
    if not cli:
        return None
    try:
        data = cli.get(key)
        if not data:
            return None
        return json.loads(data)
    except Exception:
        return None


def set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    cli = _get_client()
    if not cli:
        return
    try:
        payload = json.dumps(value, separators=(",", ":"))
        ttl = ttl_seconds if ttl_seconds is not None else settings.cache_ttl_seconds
        cli.set(key, payload, ex=max(int(ttl), 1))
    except Exception:
        pass
