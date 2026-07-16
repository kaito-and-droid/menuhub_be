import uuid
from datetime import date

from pydantic import BaseModel


class RevenueSummary(BaseModel):
    total_revenue: float
    total_cogs: float
    gross_profit: float
    profit_margin: str | None
    order_count: int
    avg_order_value: float


class RevenueByDate(BaseModel):
    date: date
    revenue: float
    cogs: float
    profit: float
    orders: int


class RevenueByCategory(BaseModel):
    category: str
    revenue: float
    cogs: float
    profit_margin: str | None


class RevenueResponse(BaseModel):
    summary: RevenueSummary
    by_date: list[RevenueByDate]
    by_category: list[RevenueByCategory]
    payment_breakdown: dict[str, float]


class LowStockAlert(BaseModel):
    id: uuid.UUID
    name: str
    current: float
    reorder_level: float
    unit: str


class IngredientSpend(BaseModel):
    name: str
    total_spent: float


class CogsSummary(BaseModel):
    total_spent: float
    start_date: date
    end_date: date
    by_ingredient: list[IngredientSpend]


class IngredientsAnalytics(BaseModel):
    low_stock_alerts: list[LowStockAlert]
    cogs_summary: CogsSummary


class TopSpender(BaseModel):
    customer_id: uuid.UUID
    name: str
    lifetime_value: float
    order_count: int
    avg_order_value: float


class CustomersAnalytics(BaseModel):
    top_spenders: list[TopSpender]
    new_customers: int
    repeat_rate: str


class OrdersByHour(BaseModel):
    hour: int
    orders: int


class OrdersAnalytics(BaseModel):
    total_orders: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    by_hour: list[OrdersByHour]
    cancellation_rate: str
