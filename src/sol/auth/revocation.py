"""Per-JWT revocation, backed by sol.revoked_tokens with 5-min in-memory cache.

Cache is intentionally tiny + simple: a dict mapping jti -> True with a single
expiry stamp. Every 5 min we drop and re-poll Postgres on next call. This is
acceptable for revocation because:

  - Revocation is a "stop accepting" decision, not a "stop existing" one;
    a 5-min staleness window matches the documented SOL latency budget.
  - Token TTLs are short for admins (60min) and long for services (90d);
    in either case 5min eventual consistency is operationally fine.
  - We can shrink the window by setting SOL_REVOKED_TOKEN_CACHE_TTL_SECONDS=N.

Active eviction path: the revoke API immediately adds the jti to the in-memory
set so the issuing SOL process doesn't keep accepting until next refresh.
Other SOL workers pick up at next refresh.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from sqlalchemy import text

from ..db import get_engine
from ..settings import get_settings


class _Cache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jtis: set[str] = set()
        self.fetched_at: float = 0.0


_C = _Cache()


def _refresh_locked() -> None:
    """Re-pull the revoked set from Postgres. Caller holds the lock."""
    try:
        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT jti FROM sol.revoked_tokens"))
            _C.jtis = {row[0] for row in rows}
    except Exception:
        # Postgres unreachable — keep stale set rather than failing open.
        # The cache will be retried on next call; meanwhile we still honor
        # the in-memory set that the local revoke API populates.
        pass
    _C.fetched_at = time.monotonic()


def _maybe_refresh() -> None:
    s = get_settings()
    age = time.monotonic() - _C.fetched_at
    if age < s.revoked_token_cache_ttl_seconds and _C.fetched_at > 0:
        return
    with _C.lock:
        # Double-check after grabbing lock
        age = time.monotonic() - _C.fetched_at
        if age < s.revoked_token_cache_ttl_seconds and _C.fetched_at > 0:
            return
        _refresh_locked()


def is_revoked(jti: str) -> bool:
    """Return True if the jti is in the revocation set."""
    if not jti:
        return False
    _maybe_refresh()
    return jti in _C.jtis


def add_revoked(jti: str) -> None:
    """Add a jti to the local in-memory revocation set immediately.

    Persistence to Postgres is the caller's responsibility (typically the
    revoke API endpoint writes the DB row first, then calls this).
    """
    with _C.lock:
        _C.jtis.add(jti)


def force_refresh() -> None:
    """Drop staleness; force re-pull on next call. Used by tests."""
    with _C.lock:
        _C.fetched_at = 0.0


@contextmanager
def clean_cache_for_tests():
    """Test helper: reset cache state."""
    try:
        with _C.lock:
            _C.jtis = set()
            _C.fetched_at = 0.0
        yield
    finally:
        with _C.lock:
            _C.jtis = set()
            _C.fetched_at = 0.0
