from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


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
