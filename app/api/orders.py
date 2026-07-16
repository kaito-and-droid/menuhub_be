import csv
import io
import uuid

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentShop, CurrentUser, DbSession
from app.core.events import publish_order_event, subscribe_order_events
from app.core.security import decode_token
from app.models import Order, OrderItem, OrderSource, OrderStatus, PaymentStatus
from app.schemas.orders import (
    OrderCreate,
    OrderCustomerOut,
    OrderItemOut,
    OrderOut,
    OrderStatusUpdate,
    PaymentStatusUpdate,
)
from app.services.audit import record_audit
from app.services.orders import create_order, transition_order

router = APIRouter(prefix="/api/shops/{shop_id}/orders", tags=["orders"])

_ORDER_LOADS = (
    selectinload(Order.items).selectinload(OrderItem.menu_item),
    selectinload(Order.customer),
    selectinload(Order.campaign),
)


def to_order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        total_amount=float(order.total_amount),
        subtotal=float(order.total_amount) + float(order.discount_amount),
        discount_amount=float(order.discount_amount),
        campaign_title=order.campaign.title if order.campaign else None,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        delivery_type=order.delivery_type,
        delivery_address=order.delivery_address,
        postal_code=order.postal_code,
        notes=order.notes,
        source=order.source,
        created_at=order.created_at,
        completed_at=order.completed_at,
        estimated_ready_at=order.estimated_time,
        customer=(
            OrderCustomerOut(
                id=order.customer.id, name=order.customer.name, phone=order.customer.phone
            )
            if order.customer
            else None
        ),
        items=[
            OrderItemOut(
                menu_item_id=item.menu_item_id,
                name=item.menu_item.name,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
                subtotal=float(item.subtotal),
                notes=item.notes,
            )
            for item in order.items
        ],
    )


async def load_order(db: DbSession, shop_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    order = await db.scalar(
        select(Order)
        .options(*_ORDER_LOADS)
        .where(Order.id == order_id, Order.shop_id == shop_id)
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.get("", response_model=list[OrderOut])
async def list_orders(
    shop: CurrentShop,
    db: DbSession,
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[OrderOut]:
    query = (
        select(Order)
        .options(*_ORDER_LOADS)
        .where(Order.shop_id == shop.id)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter is not None:
        query = query.where(Order.status == status_filter)
    orders = await db.scalars(query)
    return [to_order_out(o) for o in orders]


# NOTE: /export and /stream must be declared before /{order_id} so the literal
# segments are not swallowed by the UUID path parameter.


@router.get("/export")
async def export_orders_csv(shop: CurrentShop, db: DbSession) -> Response:
    orders = await db.scalars(
        select(Order)
        .options(*_ORDER_LOADS)
        .where(Order.shop_id == shop.id)
        .order_by(Order.created_at.desc())
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "order_number", "created_at", "completed_at", "status", "source",
            "payment_method", "payment_status", "delivery_type",
            "customer_name", "customer_phone", "postal_code", "items", "total_amount",
        ]
    )
    for order in orders:
        writer.writerow(
            [
                order.order_number,
                order.created_at.isoformat(),
                order.completed_at.isoformat() if order.completed_at else "",
                order.status.value,
                order.source.value,
                order.payment_method.value,
                order.payment_status.value,
                order.delivery_type.value,
                order.customer.name if order.customer else "",
                order.customer.phone if order.customer else "",
                order.postal_code or "",
                "; ".join(f"{i.quantity}x {i.menu_item.name}" for i in order.items),
                f"{float(order.total_amount):g}",
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


@router.get("/stream")
async def stream_orders(shop_id: uuid.UUID, token: str) -> StreamingResponse:
    """SSE stream of order events. EventSource cannot send headers, so the JWT
    arrives as a query parameter and is validated like get_current_shop."""
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    if payload.get("shop_id") != str(shop_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this shop")

    async def event_source():
        async for data in subscribe_order_events(shop_id):
            yield f"data: {data}\n\n" if data is not None else ": ping\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, shop: CurrentShop, db: DbSession) -> OrderOut:
    return to_order_out(await load_order(db, shop.id, order_id))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderOut)
async def create_order_admin(
    body: OrderCreate, shop: CurrentShop, db: DbSession
) -> OrderOut:
    order = await create_order(db, shop, body, source=OrderSource.direct_admin)
    return to_order_out(await load_order(db, shop.id, order.id))


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order_status(
    order_id: uuid.UUID,
    body: OrderStatusUpdate,
    shop: CurrentShop,
    user: CurrentUser,
    db: DbSession,
) -> OrderOut:
    order = await load_order(db, shop.id, order_id)
    await transition_order(db, shop, order, body.status, user)
    return to_order_out(await load_order(db, shop.id, order_id))


@router.patch("/{order_id}/payment", response_model=OrderOut)
async def update_payment_status(
    order_id: uuid.UUID,
    body: PaymentStatusUpdate,
    shop: CurrentShop,
    user: CurrentUser,
    db: DbSession,
) -> OrderOut:
    """Manual payment confirmation (bank transfer / PayNow)."""
    order = await load_order(db, shop.id, order_id)
    if body.payment_status != PaymentStatus.completed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only 'completed' is supported")
    if order.payment_status != PaymentStatus.pending or order.status == OrderStatus.cancelled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Payment is not awaiting confirmation")
    order.payment_status = PaymentStatus.completed
    record_audit(
        db, shop.id, user.id, "updated", "order", order.id,
        old_value={"payment_status": "pending"},
        new_value={"payment_status": "completed"},
    )
    await db.commit()
    await publish_order_event(
        shop.id,
        {
            "type": "payment_changed",
            "order_id": str(order.id),
            "order_number": order.order_number,
            "status": order.status.value,
        },
    )
    return to_order_out(await load_order(db, shop.id, order_id))


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: uuid.UUID, shop: CurrentShop, db: DbSession) -> None:
    order = await load_order(db, shop.id, order_id)
    if order.status != OrderStatus.cancelled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only cancelled orders can be deleted"
        )
    await db.delete(order)
    await db.commit()
