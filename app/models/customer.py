import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class Customer(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "customers"
    __table_args__ = (
        # Doubles as the spec's idx_customers_shop_phone index
        UniqueConstraint("shop_id", "phone", name="uq_customers_shop_phone"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    facebook_user_id: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(500))
    total_spent: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)
