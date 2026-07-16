import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.campaign import DiscountType


class CampaignBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    image_url: str | None = Field(default=None, max_length=1000)
    discount_type: DiscountType = DiscountType.none
    discount_value: float | None = Field(default=None, gt=0)
    min_order_amount: float = Field(default=0, ge=0)
    starts_at: datetime
    ends_at: datetime | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_discount(self) -> "CampaignBase":
        if self.discount_type == DiscountType.percent:
            if self.discount_value is None or not (1 <= self.discount_value <= 100):
                raise ValueError("Percent discount must be between 1 and 100")
        if self.discount_type == DiscountType.fixed and self.discount_value is None:
            raise ValueError("Fixed discount needs a value")
        if self.discount_type == DiscountType.none:
            self.discount_value = None
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    image_url: str | None = Field(default=None, max_length=1000)
    discount_type: DiscountType | None = None
    discount_value: float | None = Field(default=None, gt=0)
    min_order_amount: float | None = Field(default=None, ge=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None


class CampaignOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    image_url: str | None
    discount_type: DiscountType
    discount_value: float | None
    min_order_amount: float
    starts_at: datetime
    ends_at: datetime | None
    is_active: bool
    status: str
    discount_label: str | None


class PublicCampaign(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    image_url: str | None
    discount_type: DiscountType
    discount_value: float | None
    min_order_amount: float
    ends_at: datetime | None
    discount_label: str | None
