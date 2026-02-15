from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import redis  # type: ignore

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class _CacheState:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    failures: int = 0
    last_error: Optional[str] = None
    last_ping_ok: bool = False
    last_ping_at: Optional[float] = None
    disabled_until: Optional[float] = None


_client: Optional[redis.Redis] = None
_state = _CacheState()


def _namespaced(key: str) -> str:
    ns = (settings.cache_namespace or "spacesai").strip() or "spacesai"
    ver = (settings.cache_schema_version or "v1").strip() or "v1"
    return f"{ns}:{ver}:{key}"


def _cooldown_active() -> bool:
    if _state.disabled_until is None:
        return False
    if _state.disabled_until <= time.monotonic():
        _state.disabled_until = None
        _state.failures = 0
        return False
    return True


def _record_failure(err: Exception | str) -> None:
    _state.failures += 1
    _state.last_error = str(err)
    if settings.cache_failure_threshold > 0 and _state.failures >= settings.cache_failure_threshold:
        _state.disabled_until = time.monotonic() + max(settings.cache_cooldown_seconds, 1)
        logger.warning(
            "Valkey cache entering cooldown for %ss after %s consecutive failures",
            settings.cache_cooldown_seconds,
            _state.failures,
        )


def _mark_success() -> None:
    _state.failures = 0
    _state.disabled_until = None


def _get_client() -> Optional[redis.Redis]:
    global _client
    if not settings.valkey_host:
        return None
    if _cooldown_active():
        return None
    if _client is not None:
        return _client
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
        try:
            _client.ping()
            _state.last_ping_ok = True
            _state.last_ping_at = time.monotonic()
            _mark_success()
        except Exception as e:  # pragma: no cover - defensive
            _record_failure(e)
            logger.warning("Valkey ping failed; caching disabled until healthy")
            _client = None
            return None
        return _client
    except Exception as e:
        _record_failure(e)
        logger.warning("Valkey init failed: %s", e)
        _client = None
        return None


def get_json(key: str) -> Optional[Any]:
    cli = _get_client()
    if not cli:
        return None
    namespaced = _namespaced(key)
    try:
        data = cli.get(namespaced)
        if not data:
            _state.misses += 1
            return None
        _state.hits += 1
        return json.loads(data)
    except Exception as e:
        _record_failure(e)
        return None


def set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    cli = _get_client()
    if not cli:
        return
    namespaced = _namespaced(key)
    try:
        payload = json.dumps(value, separators=(",", ":"))
        ttl = ttl_seconds if ttl_seconds is not None else settings.cache_ttl_seconds
        cli.set(namespaced, payload, ex=max(int(ttl), 1))
        _state.sets += 1
    except Exception as e:
        _record_failure(e)


def cache_status() -> dict[str, Any]:
    cooldown_remaining = 0.0
    if _state.disabled_until:
        cooldown_remaining = max(_state.disabled_until - time.monotonic(), 0.0)
    expected = bool(settings.valkey_host)
    if not expected:
        state = "skipped"
    elif _cooldown_active():
        state = "cooldown"
    elif _client is None:
        state = "degraded"
    else:
        state = "ready"
    return {
        "expected": expected,
        "state": state,
        "connected": bool(_client),
        "hits": _state.hits,
        "misses": _state.misses,
        "sets": _state.sets,
        "failures": _state.failures,
        "last_error": _state.last_error,
        "last_ping_ok": _state.last_ping_ok,
        "cooldown_remaining": round(cooldown_remaining, 2),
    }


def reset_cache_state_for_tests() -> None:  # pragma: no cover - only used in tests
    global _client
    _client = None
    _state.hits = _state.misses = _state.sets = _state.failures = 0
    _state.last_error = None
    _state.last_ping_ok = False
    _state.last_ping_at = None
    _state.disabled_until = None


def _revision_scope(kind: str, user_id: Optional[int], space_id: Optional[int]) -> str:
    u = f"u{int(user_id) if user_id is not None else 'anon'}"
    s = f"s{int(space_id) if space_id is not None else 'all'}"
    return f"rev:{kind}:{u}:{s}"


def bump_revision(kind: str, user_id: Optional[int], space_id: Optional[int]) -> None:
    cli = _get_client()
    if not cli:
        return
    key = _namespaced(_revision_scope(kind, user_id, space_id))
    try:
        cli.incr(key)
    except Exception as e:
        _record_failure(e)


def get_revision(kind: str, user_id: Optional[int], space_id: Optional[int]) -> int:
    cli = _get_client()
    if not cli:
        return 0
    key = _namespaced(_revision_scope(kind, user_id, space_id))
    try:
        val = cli.get(key)
        return int(val) if val is not None else 0
    except Exception as e:
        _record_failure(e)
        return 0
