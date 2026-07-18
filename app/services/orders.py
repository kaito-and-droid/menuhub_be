import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import analytics_prefix, delete_prefix
from app.core.events import publish_order_event
from app.services.audit import record_audit
from app.services.campaigns import compute_discount, get_running_campaigns
from app.services.messenger import notify_order_status

from app.models import (
    AuditLog,
    Customer,
    DeliveryType,
    Ingredient,
    MenuItem,
    Order,
    OrderItem,
    OrderSource,
    OrderStatus,
    PaymentStatus,
    Shop,
    Transaction,
    TransactionType,
    User,
)
from app.schemas.orders import OrderCreate

DEFAULT_PREP_MINUTES = 15


def prep_minutes(shop: Shop) -> int:
    try:
        return max(1, int((shop.settings or {}).get("prep_minutes", DEFAULT_PREP_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_PREP_MINUTES


# status -> statuses it may move to
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.pending: {OrderStatus.preparing, OrderStatus.cancelled},
    OrderStatus.preparing: {OrderStatus.ready, OrderStatus.cancelled},
    OrderStatus.ready: {OrderStatus.completed, OrderStatus.cancelled},
    OrderStatus.completed: set(),
    OrderStatus.cancelled: set(),
}


async def _adjust_stock(
    db: AsyncSession,
    shop_id: uuid.UUID,
    order_items: list[OrderItem],
    menu_items: dict[uuid.UUID, MenuItem],
    sign: int,
) -> None:
    """Apply recipe usage to ingredient stock. sign=-1 consumes, sign=+1 restores.

    Missing/foreign ingredient ids are skipped; stock is allowed to go negative —
    a customer order must never fail on bookkeeping.
    """
    usage: dict[uuid.UUID, Decimal] = {}
    for order_item in order_items:
        menu_item = menu_items.get(order_item.menu_item_id)
        if menu_item is None:
            continue
        for line in menu_item.ingredients or []:
            try:
                ingredient_id = uuid.UUID(str(line["ingredient_id"]))
                quantity = Decimal(str(line["quantity"]))
            except (KeyError, ValueError, TypeError):
                continue
            usage[ingredient_id] = (
                usage.get(ingredient_id, Decimal(0)) + quantity * order_item.quantity
            )
    if not usage:
        return
    ingredients = await db.scalars(
        select(Ingredient).where(
            Ingredient.id.in_(usage), Ingredient.shop_id == shop_id
        )
    )
    for ingredient in ingredients:
        ingredient.current_quantity += sign * usage[ingredient.id]


async def create_order(
    db: AsyncSession, shop: Shop, body: OrderCreate, source: OrderSource
) -> Order:
    # Serialize order-number generation per shop via a row lock on the shop
    await db.execute(select(Shop.id).where(Shop.id == shop.id).with_for_update())

    item_ids = [line.menu_item_id for line in body.items]
    menu_items = {
        m.id: m
        for m in await db.scalars(
            select(MenuItem).where(MenuItem.id.in_(item_ids), MenuItem.shop_id == shop.id)
        )
    }
    for line in body.items:
        menu_item = menu_items.get(line.menu_item_id)
        if menu_item is None or not menu_item.is_available:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Menu item {line.menu_item_id} is not available"
            )

    if not shop.payment_methods.get(body.payment_method.value, False):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Payment method '{body.payment_method.value}' is not accepted by this shop",
        )

    postal = (body.postal_code or "").strip()
    if body.delivery_type == DeliveryType.delivery:
        pattern, hint = (
            (r"^\d{6}$", "6 digits") if shop.currency == "SGD" else (r"^\d{5,6}$", "5-6 digits")
        )
        if not re.fullmatch(pattern, postal):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"A valid postal code ({hint}) is required for delivery",
            )

    def variant_price(menu_item: MenuItem, variant_name: str | None) -> Decimal:
        if variant_name and menu_item.variants:
            for v in menu_item.variants:
                if v["name"] == variant_name:
                    return Decimal(str(v["price"]))
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Variant '{variant_name}' not found for item '{menu_item.name}'",
            )
        return menu_item.price

    subtotal = sum(
        (variant_price(menu_items[line.menu_item_id], line.variant_name) * line.quantity for line in body.items),
        Decimal(0),
    )
    discount, campaign = compute_discount(subtotal, await get_running_campaigns(db, shop.id))
    total = subtotal - discount
    now = datetime.now(timezone.utc)

    customer = await db.scalar(
        select(Customer).where(
            Customer.shop_id == shop.id, Customer.phone == body.customer.phone
        )
    )
    if customer is None:
        customer = Customer(
            shop_id=shop.id,
            name=body.customer.name,
            phone=body.customer.phone,
            email=body.customer.email,
            address=body.customer.address,
        )
        db.add(customer)
        await db.flush()
    else:
        customer.name = body.customer.name
        if body.customer.email:
            customer.email = body.customer.email
        if body.customer.address:
            customer.address = body.customer.address
    customer.order_count += 1
    customer.total_spent += total
    customer.last_order_at = now

    order_count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.shop_id == shop.id)
    )
    order = Order(
        shop_id=shop.id,
        customer_id=customer.id,
        campaign=campaign,
        order_number=f"#{(order_count or 0) + 1:03d}",
        status=OrderStatus.pending,
        total_amount=total,
        discount_amount=discount,
        payment_method=body.payment_method,
        payment_status=PaymentStatus.pending,
        delivery_type=body.delivery_type,
        delivery_address=body.delivery_address,
        postal_code=postal or None,
        estimated_time=now + timedelta(minutes=prep_minutes(shop)),
        notes=body.notes,
        source=source,
    )
    db.add(order)
    await db.flush()
    record_audit(
        db, shop.id, None, "created", "order", order.id,
        new_value={
            "order_number": order.order_number,
            "total_amount": float(total),
            "source": source.value,
        },
    )

    order_items = [
        OrderItem(
            order_id=order.id,
            menu_item_id=line.menu_item_id,
            variant_name=line.variant_name,
            quantity=line.quantity,
            unit_price=variant_price(menu_items[line.menu_item_id], line.variant_name),
            unit_cost=menu_items[line.menu_item_id].cost,
            subtotal=variant_price(menu_items[line.menu_item_id], line.variant_name) * line.quantity,
            notes=line.notes,
        )
        for line in body.items
    ]
    db.add_all(order_items)

    await _adjust_stock(db, shop.id, order_items, menu_items, sign=-1)
    await db.commit()
    await publish_order_event(
        shop.id,
        {
            "type": "created",
            "order_id": str(order.id),
            "order_number": order.order_number,
            "status": order.status.value,
        },
    )
    return order


async def transition_order(
    db: AsyncSession, shop: Shop, order: Order, new_status: OrderStatus, user: User | None
) -> Order:
    if new_status not in ALLOWED_TRANSITIONS[order.status]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot move order from '{order.status.value}' to '{new_status.value}'",
        )
    old_status = order.status
    order.status = new_status
    now = datetime.now(timezone.utc)

    if new_status == OrderStatus.completed:
        order.completed_at = now
        order.payment_status = PaymentStatus.completed
        db.add(
            Transaction(
                shop_id=shop.id,
                order_id=order.id,
                type=TransactionType.order,
                amount=order.total_amount,
                payment_method=order.payment_method.value,
                transaction_date=now,
            )
        )

    if new_status == OrderStatus.cancelled:
        order_items = list(
            await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
        )
        menu_items = {
            m.id: m
            for m in await db.scalars(
                select(MenuItem).where(
                    MenuItem.id.in_([i.menu_item_id for i in order_items]),
                    MenuItem.shop_id == shop.id,
                )
            )
        }
        await _adjust_stock(db, shop.id, order_items, menu_items, sign=+1)

    db.add(
        AuditLog(
            shop_id=shop.id,
            user_id=user.id if user else None,
            action="updated",
            entity_type="order",
            entity_id=order.id,
            old_value={"status": old_status.value},
            new_value={"status": new_status.value},
        )
    )
    await db.commit()
    if new_status in (OrderStatus.completed, OrderStatus.cancelled):
        # Revenue analytics change on completion/cancellation — drop cached responses
        await delete_prefix(analytics_prefix(shop.id))
    await publish_order_event(
        shop.id,
        {
            "type": "status_changed",
            "order_id": str(order.id),
            "order_number": order.order_number,
            "status": new_status.value,
        },
    )
    await notify_order_status(shop, order)
    return order
