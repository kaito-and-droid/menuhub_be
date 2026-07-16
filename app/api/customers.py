import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.orders import to_order_out
from app.core.deps import CurrentShop, DbSession
from app.models import Customer, Order, OrderItem
from app.schemas.customers import CustomerDetail, CustomerOut

router = APIRouter(prefix="/api/shops/{shop_id}/customers", tags=["customers"])


def _to_out(customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        order_count=customer.order_count,
        total_spent=float(customer.total_spent),
        last_order_at=customer.last_order_at,
        created_at=customer.created_at,
    )


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    shop: CurrentShop,
    db: DbSession,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CustomerOut]:
    customers = await db.scalars(
        select(Customer)
        .where(Customer.shop_id == shop.id)
        .order_by(Customer.last_order_at.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )
    return [_to_out(c) for c in customers]


@router.get("/{customer_id}", response_model=CustomerDetail)
async def get_customer(
    customer_id: uuid.UUID, shop: CurrentShop, db: DbSession
) -> CustomerDetail:
    customer = await db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.shop_id == shop.id)
    )
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    orders = await db.scalars(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.menu_item),
            selectinload(Order.customer),
        )
        .where(Order.customer_id == customer.id, Order.shop_id == shop.id)
        .order_by(Order.created_at.desc())
        .limit(10)
    )
    return CustomerDetail(
        **_to_out(customer).model_dump(), orders=[to_order_out(o) for o in orders]
    )
