import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import DeliveryType, OrderSource, OrderStatus, PaymentMethod, PaymentStatus


class OrderCustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=6, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=500)


class OrderItemIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(ge=1, le=100)
    notes: str | None = Field(default=None, max_length=500)


class OrderCreate(BaseModel):
    customer: OrderCustomerIn
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)
    delivery_type: DeliveryType
    delivery_address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=12)
    payment_method: PaymentMethod
    notes: str | None = Field(default=None, max_length=1000)


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class PaymentStatusUpdate(BaseModel):
    payment_status: PaymentStatus


class OrderItemOut(BaseModel):
    menu_item_id: uuid.UUID
    name: str
    quantity: int
    unit_price: float
    subtotal: float
    notes: str | None


class OrderCustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str


class OrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    status: OrderStatus
    total_amount: float
    subtotal: float
    discount_amount: float
    campaign_title: str | None
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    delivery_type: DeliveryType
    delivery_address: str | None
    postal_code: str | None
    notes: str | None
    source: OrderSource
    created_at: datetime
    completed_at: datetime | None
    estimated_ready_at: datetime | None
    customer: OrderCustomerOut | None
    items: list[OrderItemOut]


class PublicOrderCreated(BaseModel):
    id: uuid.UUID
    order_number: str
    status: OrderStatus
    total_amount: float
    subtotal: float
    discount_amount: float
    campaign_title: str | None
    estimated_ready_at: datetime | None
    currency: str = "VND"
    paynow_qr: str | None = None


class PublicOrderStatus(BaseModel):
    order_number: str
    status: OrderStatus
    total_amount: float
    created_at: datetime
    estimated_ready_at: datetime | None
    currency: str = "VND"
    payment_status: PaymentStatus
    paynow_qr: str | None = None
