import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.cache import MENU_TTL_SECONDS, get_json, menu_key, set_json
from app.core.deps import DbSession
from app.core.ratelimit import rate_limit
from app.schemas.campaigns import PublicCampaign
from app.services.campaigns import discount_label, get_running_campaigns
from app.services.orders import prep_minutes
from app.services.paynow import build_paynow_qr
from app.models import (
    MenuCategory,
    MenuItem,
    Order,
    OrderSource,
    PaymentMethod,
    PaymentStatus,
    Shop,
)
from app.schemas.menu import PublicCategoryOut, PublicItemOut, PublicMenuResponse
from app.schemas.orders import OrderCreate, PublicOrderCreated, PublicOrderStatus
from app.services.orders import create_order

router = APIRouter(prefix="/api/public/shops", tags=["public"])


async def _get_active_shop(db: DbSession, shop_slug: str) -> Shop:
    shop = await db.scalar(
        select(Shop).where(Shop.slug == shop_slug, Shop.is_active.is_(True))
    )
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shop not found")
    return shop


@router.get(
    "/{shop_slug}/menu",
    response_model=PublicMenuResponse,
    dependencies=[Depends(rate_limit("public_menu", 120))],
)
async def public_menu(shop_slug: str, db: DbSession) -> PublicMenuResponse:
    cached = await get_json(menu_key(shop_slug))
    if cached is not None:
        return PublicMenuResponse(**cached)

    shop = await _get_active_shop(db, shop_slug)

    categories = (
        await db.scalars(
            select(MenuCategory)
            .where(MenuCategory.shop_id == shop.id, MenuCategory.is_active.is_(True))
            .order_by(MenuCategory.display_order, MenuCategory.name)
        )
    ).all()
    items = (
        await db.scalars(
            select(MenuItem)
            .where(MenuItem.shop_id == shop.id, MenuItem.is_available.is_(True))
            .order_by(MenuItem.name)
        )
    ).all()

    by_category: dict[uuid.UUID | None, list[PublicItemOut]] = {}
    for item in items:
        by_category.setdefault(item.category_id, []).append(
            PublicItemOut(
                id=item.id,
                name=item.name,
                description=item.description,
                price=float(item.price),
                image_url=item.image_url,
                is_available=item.is_available,
            )
        )

    out_categories = [
        PublicCategoryOut(name=c.name, items=by_category.get(c.id, []))
        for c in categories
        if by_category.get(c.id)
    ]
    if by_category.get(None):
        out_categories.append(PublicCategoryOut(name="Menu", items=by_category[None]))

    campaigns = [
        PublicCampaign(
            id=c.id,
            title=c.title,
            description=c.description,
            image_url=c.image_url,
            discount_type=c.discount_type,
            discount_value=float(c.discount_value) if c.discount_value is not None else None,
            min_order_amount=float(c.min_order_amount or 0),
            ends_at=c.ends_at,
            discount_label=discount_label(c, shop.currency),
        )
        for c in await get_running_campaigns(db, shop.id)
    ]

    response = PublicMenuResponse(
        shop_name=shop.shop_name,
        facebook_page_id=shop.facebook_page_id,
        estimated_wait_minutes=prep_minutes(shop),
        currency=shop.currency,
        payment_methods=[
            method
            for method in ("cash", "bank_transfer", "paynow", "stripe")
            if shop.payment_methods.get(method)
        ],
        campaigns=campaigns,
        categories=out_categories,
    )
    await set_json(menu_key(shop_slug), response.model_dump(mode="json"), MENU_TTL_SECONDS)
    return response


@router.post(
    "/{shop_slug}/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=PublicOrderCreated,
    dependencies=[Depends(rate_limit("public_order", 10))],
)
async def public_create_order(
    shop_slug: str, body: OrderCreate, db: DbSession
) -> PublicOrderCreated:
    shop = await _get_active_shop(db, shop_slug)
    order = await create_order(db, shop, body, source=OrderSource.web_form)
    return PublicOrderCreated(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        total_amount=float(order.total_amount),
        subtotal=float(order.total_amount) + float(order.discount_amount),
        discount_amount=float(order.discount_amount),
        campaign_title=order.campaign.title if order.campaign else None,
        estimated_ready_at=order.estimated_time,
        currency=shop.currency,
        paynow_qr=(
            build_paynow_qr(shop, order)
            if order.payment_method == PaymentMethod.paynow
            else None
        ),
    )


@router.get(
    "/{shop_slug}/status/{order_id}",
    response_model=PublicOrderStatus,
    dependencies=[Depends(rate_limit("public_status", 120))],
)
async def public_order_status(
    shop_slug: str, order_id: uuid.UUID, db: DbSession
) -> PublicOrderStatus:
    shop = await _get_active_shop(db, shop_slug)
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.shop_id == shop.id)
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return PublicOrderStatus(
        order_number=order.order_number,
        status=order.status,
        total_amount=float(order.total_amount),
        created_at=order.created_at,
        estimated_ready_at=order.estimated_time,
        currency=shop.currency,
        payment_status=order.payment_status,
        paynow_qr=(
            build_paynow_qr(shop, order)
            if order.payment_method == PaymentMethod.paynow
            and order.payment_status == PaymentStatus.pending
            else None
        ),
    )
