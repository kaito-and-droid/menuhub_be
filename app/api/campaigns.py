import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.cache import delete as cache_delete
from app.core.cache import menu_key
from app.core.deps import CurrentShop, CurrentUser, DbSession
from app.models import Campaign, Order
from app.schemas.campaigns import CampaignCreate, CampaignOut, CampaignUpdate
from app.services.audit import changed_fields, record_audit
from app.services.campaigns import campaign_status, discount_label

router = APIRouter(prefix="/api/shops/{shop_id}/campaigns", tags=["campaigns"])

_DECIMAL_FIELDS = ("discount_value", "min_order_amount")


def _to_out(campaign: Campaign, currency: str = "VND") -> CampaignOut:
    return CampaignOut(
        id=campaign.id,
        title=campaign.title,
        description=campaign.description,
        image_url=campaign.image_url,
        discount_type=campaign.discount_type,
        discount_value=(
            float(campaign.discount_value) if campaign.discount_value is not None else None
        ),
        min_order_amount=float(campaign.min_order_amount or 0),
        starts_at=campaign.starts_at,
        ends_at=campaign.ends_at,
        is_active=campaign.is_active,
        status=campaign_status(campaign),
        discount_label=discount_label(campaign, currency),
    )


async def _get_owned_campaign(
    db: DbSession, shop_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = await db.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.shop_id == shop_id)
    )
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return campaign


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(shop: CurrentShop, db: DbSession) -> list[CampaignOut]:
    campaigns = await db.scalars(
        select(Campaign).where(Campaign.shop_id == shop.id).order_by(Campaign.created_at.desc())
    )
    return [_to_out(c, shop.currency) for c in campaigns]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CampaignOut)
async def create_campaign(
    body: CampaignCreate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> CampaignOut:
    data = body.model_dump()
    for field in _DECIMAL_FIELDS:
        if data.get(field) is not None:
            data[field] = Decimal(str(data[field]))
    campaign = Campaign(shop_id=shop.id, **data)
    db.add(campaign)
    await db.flush()
    record_audit(
        db, shop.id, user.id, "created", "campaign", campaign.id,
        new_value={"title": body.title, "discount_type": body.discount_type.value},
    )
    await db.commit()
    await cache_delete(menu_key(shop.slug))
    return _to_out(campaign, shop.currency)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    shop: CurrentShop,
    user: CurrentUser,
    db: DbSession,
) -> CampaignOut:
    campaign = await _get_owned_campaign(db, shop.id, campaign_id)
    updates = body.model_dump(exclude_unset=True)
    for field in _DECIMAL_FIELDS:
        if updates.get(field) is not None:
            updates[field] = Decimal(str(updates[field]))

    old_snapshot = {field: getattr(campaign, field) for field in updates}
    old, new = changed_fields(old_snapshot, updates)
    for field, value in updates.items():
        setattr(campaign, field, value)

    ends = campaign.ends_at
    if ends is not None and ends <= campaign.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ends_at must be after starts_at")

    if new:
        record_audit(db, shop.id, user.id, "updated", "campaign", campaign.id, old, new)
    await db.commit()
    await cache_delete(menu_key(shop.slug))
    return _to_out(campaign, shop.currency)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> None:
    campaign = await _get_owned_campaign(db, shop.id, campaign_id)
    referenced = await db.scalar(
        select(func.count()).select_from(Order).where(Order.campaign_id == campaign.id)
    )
    if referenced:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Campaign has orders attached — disable it instead of deleting",
        )
    record_audit(
        db, shop.id, user.id, "deleted", "campaign", campaign.id,
        old_value={"title": campaign.title},
    )
    await db.delete(campaign)
    await db.commit()
    await cache_delete(menu_key(shop.slug))
