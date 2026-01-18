from __future__ import annotations

from typing import Optional
from threading import RLock

# Simple in-process runtime overrides for search tuning
# Note: These are process-local and non-persistent. Use env/infra for persistent defaults.

_lock = RLock()
_default_top_k: int = 25
_pgvector_probes: Optional[int] = None
_os_num_candidates: Optional[int] = None


def get_default_top_k() -> int:
    with _lock:
        return int(_default_top_k)


def set_default_top_k(v: int) -> None:
    with _lock:
        global _default_top_k
        _default_top_k = max(int(v), 1)


def get_pgvector_probes() -> Optional[int]:
    with _lock:
        return _pgvector_probes


def set_pgvector_probes(v: Optional[int]) -> None:
    with _lock:
        global _pgvector_probes
        _pgvector_probes = int(v) if v is not None else None


def get_os_num_candidates() -> Optional[int]:
    with _lock:
        return _os_num_candidates


def set_os_num_candidates(v: Optional[int]) -> None:
    with _lock:
        global _os_num_candidates
        _os_num_candidates = int(v) if v is not None else None
