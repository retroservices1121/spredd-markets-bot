"""
Request coalescing for cache-miss thundering herd protection.

When cache expires, N simultaneous requests for the same key all try to
fetch from the platform API.  This module ensures only the first request
fetches; the rest wait on an asyncio.Lock and then re-check cache.
"""

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

# key -> (lock, last_used_timestamp)
_locks: dict[str, tuple[asyncio.Lock, float]] = {}
_LOCK_STALE_SECONDS = 300  # 5 minutes
_last_cleanup = 0.0


def _maybe_cleanup() -> None:
    """Lazily remove stale locks (checked per call, not via background task)."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _LOCK_STALE_SECONDS:
        return
    _last_cleanup = now
    stale = [
        k for k, (_, ts) in _locks.items()
        if now - ts > _LOCK_STALE_SECONDS
    ]
    for k in stale:
        _locks.pop(k, None)


async def coalesce(
    key: str,
    fetch_fn: Callable[[], Awaitable[Any]],
    recheck_cache_fn: Callable[[], Awaitable[Optional[Any]]],
) -> Any:
    """Coalesce concurrent requests for the same cache key.

    1. First caller acquires the lock and runs ``fetch_fn`` (which should
       populate the cache and return the result).
    2. Concurrent callers wait on the same lock, then call
       ``recheck_cache_fn``.  If the cache is now populated they return
       the cached value; otherwise they fall through to ``fetch_fn``
       (handles the rare case where the first fetch failed to populate
       cache).
    """
    _maybe_cleanup()

    now = time.monotonic()
    if key not in _locks:
        _locks[key] = (asyncio.Lock(), now)
    lock, _ = _locks[key]
    _locks[key] = (lock, now)  # refresh timestamp

    if lock.locked():
        # Another coroutine is already fetching — wait then recheck cache
        async with lock:
            cached = await recheck_cache_fn()
            if cached is not None:
                return cached
            # First fetch must have failed; fall through
            return await fetch_fn()
    else:
        async with lock:
            return await fetch_fn()
