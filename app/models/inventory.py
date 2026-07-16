import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin
from app.models.enums import IngredientUnit


class Ingredient(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "ingredients"
    __table_args__ = (Index("idx_ingredients_shop", "shop_id"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[IngredientUnit] = mapped_column(Enum(IngredientUnit, name="ingredient_unit"))
    current_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    last_purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    supplier_name: Mapped[str | None] = mapped_column(String(255))


class IngredientLog(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "ingredient_logs"

    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredients.id"), index=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(String(1000))
