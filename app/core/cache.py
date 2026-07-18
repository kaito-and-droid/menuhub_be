import json
import logging

from app.core.events import get_redis

logger = logging.getLogger(__name__)

MENU_TTL_SECONDS = 3600
ANALYTICS_TTL_SECONDS = 1800


# Bump the version whenever PublicMenuResponse's shape changes — stale cached
# payloads from an older schema would otherwise serve field defaults until TTL.
_MENU_SCHEMA_VERSION = 4


def menu_key(slug: str) -> str:
    return f"cache:menu:v{_MENU_SCHEMA_VERSION}:{slug}"


def analytics_prefix(shop_id) -> str:
    return f"cache:analytics:{shop_id}:"


async def get_json(key: str) -> dict | None:
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("Cache read failed for %s, treating as miss", key)
        return None


async def set_json(key: str, value: dict, ttl_seconds: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value), ex=ttl_seconds)
    except Exception:
        logger.warning("Cache write failed for %s", key)


async def delete(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception:
        logger.warning("Cache delete failed for %s", key)


async def delete_prefix(prefix: str) -> None:
    try:
        redis = get_redis()
        async for key in redis.scan_iter(match=f"{prefix}*"):
            await redis.delete(key)
    except Exception:
        logger.warning("Cache prefix delete failed for %s", prefix)
