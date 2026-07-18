import uuid

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class GalleryItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: Literal["facebook_photo", "tiktok"]
    source_url: str | None = None
    thumbnail_url: str | None = None
    embed_html: str | None = None
    sort_order: int = 0
    active: bool = True


class GalleryReorderItem(BaseModel):
    id: str
    sort_order: int


class SeoConfig(BaseModel):
    title_template: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    keywords: str | None = Field(default=None, max_length=500)
    og_image_url: str | None = Field(default=None, max_length=1000)


class OrderPageConfig(BaseModel):
    """Configurable appearance & info shown on the public order page."""
    banner_image_url: str | None = Field(default=None, max_length=1000)
    banner_headline: str | None = Field(default=None, max_length=200)
    banner_subtitle: str | None = Field(default=None, max_length=300)
    announcement: str | None = Field(default=None, max_length=300)
    announcement_style: Literal["info", "warning", "promo"] = "promo"
    show_address: bool = True
    show_phone: bool = True
    opening_hours: str | None = Field(default=None, max_length=500)
    instagram_handle: str | None = Field(default=None, max_length=100)
    tiktok_username: str | None = Field(default=None, max_length=100)
    facebook_page_url: str | None = Field(default=None, max_length=255)
    media_gallery: list[GalleryItem] = []
    menu_layout: Literal["grid", "list"] = "grid"


class TikTokAddRequest(BaseModel):
    url: str = Field(..., max_length=500)


class ShopSettingsOut(BaseModel):
    shop_name: str
    slug: str
    email: str | None
    phone: str | None
    address: str | None
    timezone: str
    currency: str
    payment_methods: dict[str, bool]
    prep_minutes: int
    paynow_proxy_type: str | None
    paynow_proxy_value: str | None
    facebook_page_id: str | None
    facebook_connected: bool
    order_page: OrderPageConfig
    seo: SeoConfig


class ShopSettingsUpdate(BaseModel):
    shop_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    payment_methods: dict[str, bool] | None = None
    prep_minutes: int | None = Field(default=None, ge=1, le=240)
    currency: Literal["VND", "SGD"] | None = None
    paynow_proxy_type: Literal["UEN", "MOBILE"] | None = None
    paynow_proxy_value: str | None = Field(default=None, max_length=20)
    facebook_page_id: str | None = Field(default=None, max_length=100)
    # Write-only: readable state is exposed as facebook_connected
    facebook_page_access_token: str | None = Field(default=None, max_length=500)
    order_page: OrderPageConfig | None = None
    seo: SeoConfig | None = None

    @field_validator("payment_methods")
    @classmethod
    def at_least_one_enabled(cls, value: dict[str, bool] | None) -> dict[str, bool] | None:
        if value is None:
            return value
        allowed = {"cash", "bank_transfer", "stripe", "paynow"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown payment methods: {sorted(unknown)}")
        if not any(value.values()):
            raise ValueError("At least one payment method must stay enabled")
        return value
