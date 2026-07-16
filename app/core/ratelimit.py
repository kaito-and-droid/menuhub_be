import logging

from fastapi import HTTPException, Request, status

from app.core.events import get_redis

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int = 60):
    """Fixed-window Redis rate limiter keyed by client IP + path params.

    Fails open: if Redis is unavailable, requests pass (availability over strictness).
    """

    async def dependency(request: Request) -> None:
        scope = ":".join(str(v) for v in request.path_params.values())
        key = f"rl:{name}:{_client_ip(request)}:{scope}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
        except Exception:
            logger.warning("Rate limiter unavailable, failing open for %s", key)
            return
        if count > limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests, slow down",
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency
