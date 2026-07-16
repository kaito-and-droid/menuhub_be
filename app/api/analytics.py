import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.core.cache import ANALYTICS_TTL_SECONDS, analytics_prefix, get_json, set_json
from app.core.deps import CurrentShop, DbSession
from app.models import (
    Customer,
    Ingredient,
    IngredientLog,
    MenuCategory,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
)
from app.schemas.analytics import (
    CogsSummary,
    CustomersAnalytics,
    IngredientsAnalytics,
    IngredientSpend,
    LowStockAlert,
    OrdersAnalytics,
    OrdersByHour,
    RevenueByCategory,
    RevenueByDate,
    RevenueResponse,
    RevenueSummary,
    TopSpender,
)
from app.services.menu import calc_margin

router = APIRouter(prefix="/api/shops/{shop_id}/analytics", tags=["analytics"])


def _default_range(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    end = end_date or datetime.now(timezone.utc).date()
    start = start_date or (end - timedelta(days=29))
    return start, end


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive date range -> half-open UTC datetime range."""
    return (
        datetime.combine(start, time.min, tzinfo=timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
    )


DateParams = Annotated[date | None, Query()]

_COGS = func.coalesce(OrderItem.unit_cost, 0) * OrderItem.quantity


async def _revenue_by_date(db, shop_id, lo, hi) -> list[RevenueByDate]:
    day = func.date(Order.completed_at)
    revenue_rows = {
        row_date: (float(revenue), int(orders))
        for row_date, revenue, orders in await db.execute(
            select(day, func.sum(Order.total_amount), func.count(Order.id))
            .where(
                Order.shop_id == shop_id,
                Order.status == OrderStatus.completed,
                Order.completed_at >= lo,
                Order.completed_at < hi,
            )
            .group_by(day)
        )
    }
    cogs_rows = {
        row_date: float(cogs or 0)
        for row_date, cogs in await db.execute(
            select(day, func.sum(_COGS))
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.shop_id == shop_id,
                Order.status == OrderStatus.completed,
                Order.completed_at >= lo,
                Order.completed_at < hi,
            )
            .group_by(day)
        )
    }
    return [
        RevenueByDate(
            date=d,
            revenue=revenue_rows[d][0],
            cogs=cogs_rows.get(d, 0),
            profit=revenue_rows[d][0] - cogs_rows.get(d, 0),
            orders=revenue_rows[d][1],
        )
        for d in sorted(revenue_rows)
    ]


@router.get("/revenue", response_model=RevenueResponse)
async def revenue_analytics(
    shop: CurrentShop,
    db: DbSession,
    start_date: DateParams = None,
    end_date: DateParams = None,
) -> RevenueResponse:
    start, end = _default_range(start_date, end_date)
    lo, hi = _bounds(start, end)

    cache_key = f"{analytics_prefix(shop.id)}revenue:{start}:{end}"
    cached = await get_json(cache_key)
    if cached is not None:
        return RevenueResponse(**cached)

    completed = (
        Order.shop_id == shop.id,
        Order.status == OrderStatus.completed,
        Order.completed_at >= lo,
        Order.completed_at < hi,
    )

    by_date = await _revenue_by_date(db, shop.id, lo, hi)
    total_revenue = sum(row.revenue for row in by_date)
    total_cogs = sum(row.cogs for row in by_date)
    order_count = sum(row.orders for row in by_date)

    category_rows = await db.execute(
        select(
            MenuCategory.name,
            func.sum(OrderItem.subtotal),
            func.sum(_COGS),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .outerjoin(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .where(*completed)
        .group_by(MenuCategory.name)
        .order_by(func.sum(OrderItem.subtotal).desc())
    )
    by_category = [
        RevenueByCategory(
            category=name or "Uncategorized",
            revenue=float(revenue),
            cogs=float(cogs or 0),
            profit_margin=calc_margin(float(revenue), float(cogs or 0)),
        )
        for name, revenue, cogs in category_rows
    ]

    payment_rows = await db.execute(
        select(Order.payment_method, func.sum(Order.total_amount))
        .where(*completed)
        .group_by(Order.payment_method)
    )
    payment_breakdown = {method.value: float(amount) for method, amount in payment_rows}

    response = RevenueResponse(
        summary=RevenueSummary(
            total_revenue=total_revenue,
            total_cogs=total_cogs,
            gross_profit=total_revenue - total_cogs,
            profit_margin=calc_margin(total_revenue, total_cogs),
            order_count=order_count,
            avg_order_value=round(total_revenue / order_count, 2) if order_count else 0,
        ),
        by_date=by_date,
        by_category=by_category,
        payment_breakdown=payment_breakdown,
    )
    await set_json(cache_key, response.model_dump(mode="json"), ANALYTICS_TTL_SECONDS)
    return response


@router.get("/revenue/export")
async def export_revenue_csv(
    shop: CurrentShop,
    db: DbSession,
    start_date: DateParams = None,
    end_date: DateParams = None,
) -> Response:
    start, end = _default_range(start_date, end_date)
    lo, hi = _bounds(start, end)
    by_date = await _revenue_by_date(db, shop.id, lo, hi)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "revenue", "cogs", "profit", "orders"])
    for row in by_date:
        writer.writerow(
            [row.date.isoformat(), f"{row.revenue:g}", f"{row.cogs:g}", f"{row.profit:g}", row.orders]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="revenue_{start}_{end}.csv"'
        },
    )


@router.get("/ingredients", response_model=IngredientsAnalytics)
async def ingredients_analytics(
    shop: CurrentShop,
    db: DbSession,
    start_date: DateParams = None,
    end_date: DateParams = None,
) -> IngredientsAnalytics:
    start, end = _default_range(start_date, end_date)
    lo, hi = _bounds(start, end)

    low = await db.scalars(
        select(Ingredient)
        .where(
            Ingredient.shop_id == shop.id,
            Ingredient.current_quantity <= Ingredient.reorder_level,
        )
        .order_by(Ingredient.name)
    )
    spend_rows = (
        await db.execute(
            select(Ingredient.name, func.sum(IngredientLog.cost))
            .join(Ingredient, Ingredient.id == IngredientLog.ingredient_id)
            .where(
                IngredientLog.shop_id == shop.id,
                IngredientLog.purchase_date >= lo,
                IngredientLog.purchase_date < hi,
            )
            .group_by(Ingredient.name)
            .order_by(func.sum(IngredientLog.cost).desc())
        )
    ).all()

    return IngredientsAnalytics(
        low_stock_alerts=[
            LowStockAlert(
                id=i.id,
                name=i.name,
                current=float(i.current_quantity),
                reorder_level=float(i.reorder_level),
                unit=i.unit.value,
            )
            for i in low
        ],
        cogs_summary=CogsSummary(
            total_spent=sum(float(total) for _, total in spend_rows),
            start_date=start,
            end_date=end,
            by_ingredient=[
                IngredientSpend(name=name, total_spent=float(total))
                for name, total in spend_rows
            ],
        ),
    )


@router.get("/customers", response_model=CustomersAnalytics)
async def customers_analytics(
    shop: CurrentShop,
    db: DbSession,
    start_date: DateParams = None,
    end_date: DateParams = None,
) -> CustomersAnalytics:
    start, end = _default_range(start_date, end_date)
    lo, hi = _bounds(start, end)

    top = await db.scalars(
        select(Customer)
        .where(Customer.shop_id == shop.id, Customer.order_count > 0)
        .order_by(Customer.total_spent.desc())
        .limit(10)
    )
    new_customers = await db.scalar(
        select(func.count())
        .select_from(Customer)
        .where(Customer.shop_id == shop.id, Customer.created_at >= lo, Customer.created_at < hi)
    )
    total = await db.scalar(
        select(func.count()).select_from(Customer).where(Customer.shop_id == shop.id)
    )
    repeat = await db.scalar(
        select(func.count())
        .select_from(Customer)
        .where(Customer.shop_id == shop.id, Customer.order_count > 1)
    )

    return CustomersAnalytics(
        top_spenders=[
            TopSpender(
                customer_id=c.id,
                name=c.name,
                lifetime_value=float(c.total_spent),
                order_count=c.order_count,
                avg_order_value=round(float(c.total_spent) / c.order_count, 2) if c.order_count else 0,
            )
            for c in top
        ],
        new_customers=new_customers or 0,
        repeat_rate=f"{round((repeat or 0) / total * 100)}%" if total else "0%",
    )


@router.get("/orders", response_model=OrdersAnalytics)
async def orders_analytics(
    shop: CurrentShop,
    db: DbSession,
    start_date: DateParams = None,
    end_date: DateParams = None,
) -> OrdersAnalytics:
    start, end = _default_range(start_date, end_date)
    lo, hi = _bounds(start, end)
    in_range = (Order.shop_id == shop.id, Order.created_at >= lo, Order.created_at < hi)

    status_rows = (
        await db.execute(
            select(Order.status, func.count()).where(*in_range).group_by(Order.status)
        )
    ).all()
    source_rows = (
        await db.execute(
            select(Order.source, func.count()).where(*in_range).group_by(Order.source)
        )
    ).all()
    hour_expr = func.extract("hour", Order.created_at)
    hour_rows = (
        await db.execute(
            select(hour_expr, func.count()).where(*in_range).group_by(hour_expr)
        )
    ).all()

    by_status = {s.value: int(c) for s, c in status_rows}
    total = sum(by_status.values())
    cancelled = by_status.get("cancelled", 0)
    hour_counts = {int(h): int(c) for h, c in hour_rows}

    return OrdersAnalytics(
        total_orders=total,
        by_status=by_status,
        by_source={s.value: int(c) for s, c in source_rows},
        by_hour=[OrdersByHour(hour=h, orders=hour_counts.get(h, 0)) for h in range(24)],
        cancellation_rate=f"{round(cancelled / total * 100)}%" if total else "0%",
    )
