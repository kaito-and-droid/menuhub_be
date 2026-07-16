import json
import logging
import uuid
from collections.abc import AsyncIterator
from functools import lru_cache

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 15


@lru_cache
def get_redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def _channel(shop_id: uuid.UUID) -> str:
    return f"shop:{shop_id}:orders"


async def publish_order_event(shop_id: uuid.UUID, event: dict) -> None:
    """Fire-and-forget: a broken Redis must never fail an order request."""
    try:
        await get_redis().publish(_channel(shop_id), json.dumps(event))
    except Exception:
        logger.exception("Failed to publish order event for shop %s", shop_id)


async def subscribe_order_events(shop_id: uuid.UUID) -> AsyncIterator[str | None]:
    """Yields event JSON strings; yields None once subscribed and then on every
    keepalive interval so the SSE endpoint can emit pings."""
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(_channel(shop_id))
    try:
        yield None  # subscription active — lets the endpoint confirm the stream
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=KEEPALIVE_SECONDS
            )
            yield message["data"] if message else None
    finally:
        await pubsub.unsubscribe(_channel(shop_id))
        await pubsub.aclose()
