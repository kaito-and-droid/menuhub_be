import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class DiscountType(str, enum.Enum):
    none = "none"  # informational banner only
    percent = "percent"
    fixed = "fixed"


class Campaign(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "campaigns"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    discount_type: Mapped[DiscountType] = mapped_column(
        Enum(DiscountType, name="discount_type"), default=DiscountType.none
    )
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_order_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
