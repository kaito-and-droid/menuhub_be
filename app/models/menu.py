import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class MenuCategory(Base, UUIDPkMixin):
    __tablename__ = "menu_categories"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    items: Mapped[list["MenuItem"]] = relationship(back_populates="category")


class MenuItem(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "menu_items"
    __table_args__ = (Index("idx_menu_items_shop", "shop_id"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("menu_categories.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    # Recipe: [{ingredient_id, quantity, unit}]
    ingredients: Mapped[list] = mapped_column(JSONB, default=list)
    # Variants: [{name, price, cost?}] — null/empty means single-price item
    variants: Mapped[list | None] = mapped_column(JSONB, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[MenuCategory | None] = relationship(back_populates="items")
