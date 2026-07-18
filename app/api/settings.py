from fastapi import APIRouter, HTTPException, status

from app.core.cache import delete as cache_delete
from app.core.cache import menu_key
from app.core.deps import CurrentShop, CurrentUser, DbSession
from app.models import Shop, UserRole
from app.schemas.settings import (
    GalleryItem,
    OrderPageConfig,
    SeoConfig,
    ShopSettingsOut,
    ShopSettingsUpdate,
    TikTokAddRequest,
)
from app.services.audit import MASK, changed_fields, record_audit
from app.services.gallery import fetch_tiktok_oembed, sync_facebook_photos
from app.services.orders import prep_minutes

router = APIRouter(prefix="/api/shops/{shop_id}/settings", tags=["settings"])


def _to_out(shop: Shop) -> ShopSettingsOut:
    shop_settings = shop.settings or {}
    order_page_data = shop_settings.get("order_page") or {}
    order_page = OrderPageConfig(
        banner_image_url=order_page_data.get("banner_image_url"),
        banner_headline=order_page_data.get("banner_headline"),
        banner_subtitle=order_page_data.get("banner_subtitle"),
        announcement=order_page_data.get("announcement"),
        announcement_style=order_page_data.get("announcement_style", "promo"),
        show_address=order_page_data.get("show_address", True),
        show_phone=order_page_data.get("show_phone", True),
        opening_hours=order_page_data.get("opening_hours"),
        instagram_handle=order_page_data.get("instagram_handle"),
        tiktok_username=order_page_data.get("tiktok_username"),
        facebook_page_url=order_page_data.get("facebook_page_url"),
        media_gallery=order_page_data.get("media_gallery", []),
    )
    seo_data = shop_settings.get("seo") or {}
    seo = SeoConfig(
        title_template=seo_data.get("title_template"),
        description=seo_data.get("description"),
        keywords=seo_data.get("keywords"),
        og_image_url=seo_data.get("og_image_url"),
    )
    return ShopSettingsOut(
        shop_name=shop.shop_name,
        slug=shop.slug,
        email=shop.email,
        phone=shop.phone,
        address=shop.address,
        timezone=shop.timezone,
        currency=shop.currency,
        payment_methods=shop.payment_methods,
        prep_minutes=prep_minutes(shop),
        paynow_proxy_type=shop_settings.get("paynow_proxy_type"),
        paynow_proxy_value=shop_settings.get("paynow_proxy_value"),
        facebook_page_id=shop.facebook_page_id,
        facebook_connected=bool(shop.facebook_page_id and shop.facebook_app_access_token),
        order_page=order_page,
        seo=seo,
    )


@router.get("", response_model=ShopSettingsOut)
async def get_settings(shop: CurrentShop) -> ShopSettingsOut:
    return _to_out(shop)


@router.patch("", response_model=ShopSettingsOut)
async def update_settings(
    body: ShopSettingsUpdate, shop: CurrentShop, user: CurrentUser, db: DbSession
) -> ShopSettingsOut:
    if user.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change settings")

    updates = body.model_dump(exclude_unset=True)
    audit_updates = dict(updates)
    if "facebook_page_access_token" in audit_updates:
        audit_updates["facebook_page_access_token"] = MASK

    shop_settings = shop.settings or {}
    old_snapshot = {
        "shop_name": shop.shop_name,
        "email": shop.email,
        "phone": shop.phone,
        "address": shop.address,
        "payment_methods": shop.payment_methods,
        "prep_minutes": prep_minutes(shop),
        "currency": shop.currency,
        "paynow_proxy_type": shop_settings.get("paynow_proxy_type"),
        "paynow_proxy_value": shop_settings.get("paynow_proxy_value"),
        "facebook_page_id": shop.facebook_page_id,
        "facebook_page_access_token": MASK if shop.facebook_app_access_token else None,
        "order_page": shop_settings.get("order_page"),
        "seo": shop_settings.get("seo"),
    }

    # PayNow eligibility must hold for the post-update state
    next_currency = updates.get("currency", shop.currency)
    next_methods = updates.get("payment_methods", shop.payment_methods)
    next_proxy_type = updates.get("paynow_proxy_type", shop_settings.get("paynow_proxy_type"))
    next_proxy_value = updates.get("paynow_proxy_value", shop_settings.get("paynow_proxy_value"))
    if next_methods.get("paynow"):
        if next_currency != "SGD":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "PayNow requires the shop currency to be SGD"
            )
        if not (next_proxy_type and next_proxy_value):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Configure your PayNow UEN or mobile number before enabling PayNow",
            )

    if "facebook_page_access_token" in updates:
        token = updates.pop("facebook_page_access_token")
        shop.facebook_app_access_token = token or None
    # Reassign the JSONB dict so SQLAlchemy sees the change
    new_settings = dict(shop_settings)
    for nested_field in ("order_page", "seo"):
        if nested_field in updates:
            val = updates.pop(nested_field)
            if val is not None:
                new_settings[nested_field] = val
            else:
                new_settings.pop(nested_field, None)

    for json_field in ("prep_minutes", "paynow_proxy_type", "paynow_proxy_value"):
        if json_field in updates:
            value = updates.pop(json_field)
            if value is None:
                new_settings.pop(json_field, None)
            else:
                new_settings[json_field] = value
    shop.settings = new_settings
    for field, value in updates.items():
        setattr(shop, field, value)

    old, new = changed_fields(old_snapshot, audit_updates)
    if new:
        record_audit(db, shop.id, user.id, "updated", "shop_settings", shop.id, old, new)
    await db.commit()
    await db.refresh(shop)
    # Public menu embeds shop name, page id, and wait minutes
    await cache_delete(menu_key(shop.slug))
    return _to_out(shop)


def _get_media_gallery(shop: Shop) -> list[dict]:
    shop_settings = shop.settings or {}
    order_page = shop_settings.get("order_page", {})
    return list(order_page.get("media_gallery", []))


def _set_media_gallery(shop: Shop, items: list[dict]) -> None:
    shop_settings = dict(shop.settings or {})
    order_page = dict(shop_settings.get("order_page", {}))
    order_page["media_gallery"] = items
    shop_settings["order_page"] = order_page
    shop.settings = shop_settings


@router.post("/gallery/sync-facebook", response_model=list[GalleryItem])
async def sync_facebook_gallery(
    shop: CurrentShop, user: CurrentUser, db: DbSession
) -> list[GalleryItem]:
    if user.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can manage gallery")
    fb_items = await sync_facebook_photos(shop)
    existing = _get_media_gallery(shop)
    kept = [item for item in existing if item.get("source") != "facebook_photo"]
    merged = kept + fb_items
    _set_media_gallery(shop, merged)
    await db.commit()
    await db.refresh(shop)
    await cache_delete(menu_key(shop.slug))
    return [GalleryItem(**item) for item in _get_media_gallery(shop)]


@router.post("/gallery/tiktok", response_model=list[GalleryItem])
async def add_tiktok_video(
    body: TikTokAddRequest,
    shop: CurrentShop,
    user: CurrentUser,
    db: DbSession,
) -> list[GalleryItem]:
    if user.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can manage gallery")
    item = await fetch_tiktok_oembed(body.url)
    if item is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid TikTok URL or video not found")
    existing = _get_media_gallery(shop)
    item["sort_order"] = len(existing)
    existing.append(item)
    _set_media_gallery(shop, existing)
    await db.commit()
    await db.refresh(shop)
    await cache_delete(menu_key(shop.slug))
    return [GalleryItem(**item) for item in _get_media_gallery(shop)]


@router.delete("/gallery/{item_id}", response_model=list[GalleryItem])
async def delete_gallery_item(
    item_id: str,
    shop: CurrentShop,
    user: CurrentUser,
    db: DbSession,
) -> list[GalleryItem]:
    if user.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can manage gallery")
    existing = _get_media_gallery(shop)
    filtered = [item for item in existing if item.get("id") != item_id]
    _set_media_gallery(shop, filtered)
    await db.commit()
    await db.refresh(shop)
    await cache_delete(menu_key(shop.slug))
    return [GalleryItem(**item) for item in _get_media_gallery(shop)]


@router.put("/gallery/reorder", response_model=list[GalleryItem])
async def reorder_gallery(
    body: list[dict],
    shop: CurrentShop,
    user: CurrentUser,
    db: DbSession,
) -> list[GalleryItem]:
    if user.role != UserRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can manage gallery")
    existing = _get_media_gallery(shop)
    id_order = {item["id"]: item["sort_order"] for item in body}
    for item in existing:
        if item["id"] in id_order:
            item["sort_order"] = id_order[item["id"]]
    existing.sort(key=lambda x: x.get("sort_order", 0))
    _set_media_gallery(shop, existing)
    await db.commit()
    await db.refresh(shop)
    await cache_delete(menu_key(shop.slug))
    return [GalleryItem(**item) for item in _get_media_gallery(shop)]
