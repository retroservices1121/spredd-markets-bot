"""
Rate limiting setup using slowapi.

Uses Redis as storage backend when available, falls back to in-memory
storage — matches our graceful degradation pattern.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ..config import get_settings


def _get_redis_uri() -> str | None:
    """Return the Redis URL from settings, or None."""
    try:
        s = get_settings()
        return s.redis_url or None
    except Exception:
        return None


def _make_limiter() -> Limiter:
    """Create a Limiter with Redis (preferred) or in-memory backend."""
    settings = get_settings()
    redis_url = _get_redis_uri()
    storage_uri = f"{redis_url}/1" if redis_url else "memory://"

    return Limiter(
        key_func=get_remote_address,
        default_limits=[settings.rate_limit_global],
        storage_uri=storage_uri,
        strategy="fixed-window",
    )


limiter = _make_limiter()


def get_user_key(request: Request) -> str:
    """Key function for per-user rate limiting on trading endpoints."""
    # Prefer user ID from auth dependency (set in get_current_user)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a clean 429 response with retry_after."""
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": f"Rate limit exceeded: {exc.detail}",
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
