import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.orders import OrderOut


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str
    email: str | None
    address: str | None
    order_count: int
    total_spent: float
    last_order_at: datetime | None
    created_at: datetime


class CustomerDetail(CustomerOut):
    orders: list[OrderOut]
