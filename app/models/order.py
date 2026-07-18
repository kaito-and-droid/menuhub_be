import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin
from app.models.campaign import Campaign
from app.models.customer import Customer
from app.models.enums import DeliveryType, OrderSource, OrderStatus, PaymentMethod, PaymentStatus
from app.models.menu import MenuItem


class Order(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_shop_created", "shop_id", "created_at"),
        Index("idx_orders_status", "shop_id", "status"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    order_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), default=OrderStatus.pending
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    payment_method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod, name="payment_method"))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.pending
    )
    delivery_type: Mapped[DeliveryType] = mapped_column(Enum(DeliveryType, name="delivery_type"))
    delivery_address: Mapped[str | None] = mapped_column(String(500))
    postal_code: Mapped[str | None] = mapped_column(String(12))
    estimated_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[OrderSource] = mapped_column(Enum(OrderSource, name="order_source"))
    messenger_user_id: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    customer: Mapped["Customer | None"] = relationship()
    campaign: Mapped["Campaign | None"] = relationship()


class OrderItem(Base, UUIDPkMixin):
    __tablename__ = "order_items"
    __table_args__ = (Index("idx_order_items_order", "order_id"),)

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"))
    variant_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # COGS snapshot taken at order time so later menu cost edits don't rewrite history
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(String(500))

    order: Mapped[Order] = relationship(back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship()
