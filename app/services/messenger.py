import logging

import httpx

from app.core.config import get_settings
from app.models import Order, OrderStatus, Shop

logger = logging.getLogger(__name__)

STATUS_MESSAGES = {
    OrderStatus.pending: "We received your order {n}. We'll let you know when it's being prepared. ☕",
    OrderStatus.preparing: "Your order {n} is being prepared. 👨‍🍳",
    OrderStatus.ready: "Your order {n} is ready! 🎉 Come pick it up.",
    OrderStatus.completed: "Order {n} is done — thank you! See you again soon. 🙏",
    OrderStatus.cancelled: "Sorry, your order {n} was cancelled. Message us if you have questions.",
}


async def _graph_post(path: str, payload: dict, token: str) -> None:
    """Single seam for all Graph API calls (monkeypatched in tests)."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{get_settings().facebook_graph_url}{path}",
            params={"access_token": token},
            json=payload,
        )
        response.raise_for_status()


async def send_text(shop: Shop, recipient_id: str, text: str) -> None:
    """Fire-and-forget: a Messenger failure must never break an order request."""
    if not (shop.facebook_page_id and shop.facebook_app_access_token):
        return
    try:
        await _graph_post(
            "/me/messages",
            {"recipient": {"id": recipient_id}, "message": {"text": text}},
            shop.facebook_app_access_token,
        )
    except Exception:
        logger.exception(
            "Failed to send Messenger message for shop %s to %s", shop.id, recipient_id
        )


async def notify_order_status(shop: Shop, order: Order) -> None:
    if not order.messenger_user_id:
        return
    template = STATUS_MESSAGES.get(order.status)
    if template is None:
        return
    await send_text(shop, order.messenger_user_id, template.format(n=order.order_number))
