import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, DiscountType


def campaign_status(campaign: Campaign, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not campaign.is_active:
        return "disabled"
    if campaign.starts_at > now:
        return "scheduled"
    if campaign.ends_at is not None and campaign.ends_at <= now:
        return "expired"
    return "running"


async def get_running_campaigns(db: AsyncSession, shop_id: uuid.UUID) -> list[Campaign]:
    now = datetime.now(timezone.utc)
    return list(
        await db.scalars(
            select(Campaign)
            .where(
                Campaign.shop_id == shop_id,
                Campaign.is_active.is_(True),
                Campaign.starts_at <= now,
                or_(Campaign.ends_at.is_(None), Campaign.ends_at > now),
            )
            .order_by(Campaign.created_at.desc())
        )
    )


def compute_discount(
    subtotal: "Decimal", campaigns: list[Campaign]
) -> tuple["Decimal", Campaign | None]:
    """Best single discount among running campaigns — no stacking. Decimal in/out."""
    best_amount, best_campaign = Decimal(0), None
    for campaign in campaigns:
        if campaign.discount_type == DiscountType.none or campaign.discount_value is None:
            continue
        if subtotal < (campaign.min_order_amount or Decimal(0)):
            continue
        if campaign.discount_type == DiscountType.percent:
            amount = (subtotal * campaign.discount_value / 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            amount = min(Decimal(campaign.discount_value), subtotal)
        if amount > best_amount:
            best_amount, best_campaign = amount, campaign
    return best_amount, best_campaign


def format_money(amount, currency: str) -> str:
    value = float(amount)
    if currency == "SGD":
        return f"S${value:,.2f}"
    return f"{int(round(value)):,}".replace(",", ".") + "₫"


def discount_label(campaign: Campaign, currency: str = "VND") -> str | None:
    if campaign.discount_type == DiscountType.none or campaign.discount_value is None:
        return None
    if campaign.discount_type == DiscountType.percent:
        label = f"-{int(campaign.discount_value)}%"
    else:
        label = f"-{format_money(campaign.discount_value, currency)}"
    if (campaign.min_order_amount or Decimal(0)) > 0:
        label += f" · orders from {format_money(campaign.min_order_amount, currency)}"
    return label
