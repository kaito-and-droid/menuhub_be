import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin
from app.models.enums import TransactionType


class Transaction(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "transactions"
    __table_args__ = (Index("idx_transactions_shop_date", "shop_id", "transaction_date"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType, name="transaction_type"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category: Mapped[str | None] = mapped_column(String(100))
    payment_method: Mapped[str | None] = mapped_column(String(50))
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))


class AuditLog(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "audit_logs"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
