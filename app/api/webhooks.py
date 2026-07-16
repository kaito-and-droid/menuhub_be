import hashlib
import hmac
import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import DbSession
from app.models import Order, Shop
from app.services.campaigns import format_money
from app.services.messenger import send_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ORDER_NUMBER_RE = re.compile(r"#\d+")
ORDER_REF_RE = re.compile(r"^order:([0-9a-f-]{36})$")


@router.get("/facebook", response_class=PlainTextResponse)
async def verify_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
) -> str:
    if mode == "subscribe" and verify_token == get_settings().facebook_verify_token:
        return challenge
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification failed")


def _check_signature(raw_body: bytes, signature_header: str | None) -> None:
    secret = get_settings().facebook_app_secret
    if not secret:  # dev mode — no secret configured
        return
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not (signature_header and hmac.compare_digest(expected, signature_header)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")


async def _handle_referral(db, shop: Shop, sender_id: str, ref: str | None) -> None:
    match = ORDER_REF_RE.match(ref or "")
    if match is None:
        await _send_greeting(db, shop, sender_id)
        return
    order = await db.scalar(
        select(Order).where(Order.id == uuid.UUID(match.group(1)), Order.shop_id == shop.id)
    )
    if order is None:
        return
    order.messenger_user_id = sender_id
    await db.commit()
    await send_text(
        shop, sender_id, f"You'll get updates for order {order.order_number} here 🎉"
    )


async def _send_greeting(db, shop: Shop, sender_id: str) -> None:
    await send_text(
        shop,
        sender_id,
        f"Hi! 👋 Welcome to {shop.shop_name}. "
        f"Order here: {get_settings().frontend_url}/order/{shop.slug} — "
        'or send your order number (e.g. "#012") to check its status.',
    )


async def _handle_message(db, shop: Shop, sender_id: str, text: str) -> None:
    match = ORDER_NUMBER_RE.search(text)
    if match:
        order = await db.scalar(
            select(Order).where(Order.order_number == match.group(0), Order.shop_id == shop.id)
        )
        if order is not None:
            await send_text(
                shop,
                sender_id,
                f"Order {order.order_number}: {order.status.value} · "
                f"total {format_money(order.total_amount, shop.currency)}",
            )
            return
    await _send_greeting(db, shop, sender_id)


@router.post("/facebook")
async def facebook_webhook(request: Request, db: DbSession) -> dict:
    raw_body = await request.body()
    _check_signature(raw_body, request.headers.get("X-Hub-Signature-256"))
    data = await request.json()

    if data.get("object") != "page":
        return {"status": "ignored"}

    for entry in data.get("entry", []):
        shop = await db.scalar(
            select(Shop).where(Shop.facebook_page_id == str(entry.get("id")))
        )
        if shop is None:
            logger.warning("Webhook for unknown page id %s", entry.get("id"))
            continue
        for messaging in entry.get("messaging", []):
            sender_id = messaging.get("sender", {}).get("id")
            if not sender_id:
                continue
            referral = messaging.get("referral") or messaging.get("postback", {}).get(
                "referral"
            )
            try:
                if referral is not None:
                    await _handle_referral(db, shop, sender_id, referral.get("ref"))
                elif messaging.get("postback"):
                    await _send_greeting(db, shop, sender_id)
                elif messaging.get("message", {}).get("text"):
                    await _handle_message(
                        db, shop, sender_id, messaging["message"]["text"]
                    )
            except Exception:
                # Never bounce the webhook — Facebook retries aggressively on errors
                logger.exception("Error handling messaging event for shop %s", shop.id)

    return {"status": "ok"}
