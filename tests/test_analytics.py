import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from tests.conftest import auth_headers, register_shop
from tests.test_orders import order_body, setup_shop


async def complete_order(client, tokens, headers, item_id, phone, qty=2, completed_at=None):
    """Place a public order, walk it to completed, optionally rewrite completed_at."""
    slug = tokens["shop_slug"]
    order = (
        await client.post(
            f"/api/public/shops/{slug}/orders",
            json=order_body(item_id, quantity=qty, phone=phone),
        )
    ).json()
    base = f"/api/shops/{tokens['shop_id']}/orders"
    for next_status in ("preparing", "ready", "completed"):
        resp = await client.patch(
            f"{base}/{order['id']}", json={"status": next_status}, headers=headers
        )
        assert resp.status_code == 200, resp.text
    if completed_at is not None:
        from app.db import get_sessionmaker
        from app.models import Order

        async with get_sessionmaker()() as session:
            await session.execute(
                update(Order)
                .where(Order.id == uuid.UUID(order["id"]))
                .values(completed_at=completed_at)
            )
            await session.commit()
    return order


async def test_revenue_analytics_summary_and_buckets(client):
    tokens, headers, ingredient, item = await setup_shop(client, "ana")
    base = f"/api/shops/{tokens['shop_id']}/analytics"
    now = datetime.now(timezone.utc)

    # Two completed orders on different days + one pending + one cancelled (both excluded)
    await complete_order(client, tokens, headers, item["id"], "0911111111", qty=2)
    await complete_order(
        client, tokens, headers, item["id"], "0922222222", qty=1,
        completed_at=now - timedelta(days=10),
    )
    slug = tokens["shop_slug"]
    await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], phone="0933333333"))
    cancelled = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], phone="0944444444"))
    ).json()
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/orders/{cancelled['id']}",
        json={"status": "cancelled"},
        headers=headers,
    )

    data = (await client.get(f"{base}/revenue", headers=headers)).json()
    summary = data["summary"]
    assert summary["total_revenue"] == 165000
    assert summary["total_cogs"] == 45000
    assert summary["gross_profit"] == 120000
    assert summary["profit_margin"] == "73%"
    assert summary["order_count"] == 2
    assert summary["avg_order_value"] == 82500

    assert len(data["by_date"]) == 2
    assert data["payment_breakdown"] == {"cash": 165000}
    assert data["by_category"] == [
        {"category": "Uncategorized", "revenue": 165000, "cogs": 45000, "profit_margin": "73%"}
    ]

    # Date filter: only today's order
    today = now.date().isoformat()
    filtered = (
        await client.get(f"{base}/revenue?start_date={today}", headers=headers)
    ).json()
    assert filtered["summary"]["total_revenue"] == 110000
    assert filtered["summary"]["order_count"] == 1


async def test_cogs_uses_cost_snapshot(client):
    tokens, headers, ingredient, item = await setup_shop(client, "snap")
    await complete_order(client, tokens, headers, item["id"], "0955555555", qty=2)

    # Raising the menu cost afterwards must not rewrite history
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/menu/items/{item['id']}",
        json={"cost": 50000},
        headers=headers,
    )
    data = (
        await client.get(f"/api/shops/{tokens['shop_id']}/analytics/revenue", headers=headers)
    ).json()
    assert data["summary"]["total_cogs"] == 30000  # 2 × 15000 snapshot


async def test_customers_analytics(client):
    tokens, headers, ingredient, item = await setup_shop(client, "cust-ana")
    await complete_order(client, tokens, headers, item["id"], "0901000001", qty=1)
    await complete_order(client, tokens, headers, item["id"], "0901000002", qty=1)
    await complete_order(client, tokens, headers, item["id"], "0901000002", qty=2)

    data = (
        await client.get(f"/api/shops/{tokens['shop_id']}/analytics/customers", headers=headers)
    ).json()
    assert data["new_customers"] == 2
    assert data["repeat_rate"] == "50%"
    top = data["top_spenders"]
    assert top[0]["lifetime_value"] == 165000
    assert top[0]["order_count"] == 2
    assert top[1]["lifetime_value"] == 55000


async def test_ingredients_analytics(client):
    tokens, headers, ingredient, item = await setup_shop(client, "ing-ana")
    base = f"/api/shops/{tokens['shop_id']}"

    await client.post(
        f"{base}/ingredients/logs",
        json={"ingredient_id": ingredient["id"], "quantity": 500, "cost": 200000},
        headers=headers,
    )
    # Force low stock (current 1500 after purchase)
    await client.patch(
        f"{base}/ingredients/{ingredient['id']}", json={"reorder_level": 2000}, headers=headers
    )

    data = (await client.get(f"{base}/analytics/ingredients", headers=headers)).json()
    assert [a["name"] for a in data["low_stock_alerts"]] == ["Coffee Beans"]
    assert data["cogs_summary"]["total_spent"] == 200000
    assert data["cogs_summary"]["by_ingredient"] == [
        {"name": "Coffee Beans", "total_spent": 200000}
    ]


async def test_csv_exports(client):
    tokens, headers, ingredient, item = await setup_shop(client, "csv")
    await complete_order(client, tokens, headers, item["id"], "0906000001", qty=2)

    resp = await client.get(
        f"/api/shops/{tokens['shop_id']}/analytics/revenue/export", headers=headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == "date,revenue,cogs,profit,orders"
    assert len(lines) == 2
    assert ",110000,30000,80000,1" in lines[1]

    resp = await client.get(f"/api/shops/{tokens['shop_id']}/orders/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "2x Cappuccino" in resp.text
    assert "#001" in resp.text


async def test_analytics_tenancy(client):
    shop_a = await register_shop(client, "ana-a")
    shop_b = await register_shop(client, "ana-b")
    for path in ("revenue", "ingredients", "customers", "orders", "revenue/export"):
        resp = await client.get(
            f"/api/shops/{shop_b['shop_id']}/analytics/{path}", headers=auth_headers(shop_a)
        )
        assert resp.status_code == 403


async def test_orders_analytics(client):
    tokens, headers, ingredient, item = await setup_shop(client, "ord-ana")
    slug = tokens["shop_slug"]
    base = f"/api/shops/{tokens['shop_id']}"

    await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], phone="0930000001"))
    await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], phone="0930000002"))
    manual = (
        await client.post(f"{base}/orders", json=order_body(item["id"], phone="0930000003"), headers=headers)
    ).json()
    await client.patch(f"{base}/orders/{manual['id']}", json={"status": "cancelled"}, headers=headers)

    data = (await client.get(f"{base}/analytics/orders", headers=headers)).json()
    assert data["total_orders"] == 3
    assert data["by_status"] == {"pending": 2, "cancelled": 1}
    assert data["by_source"] == {"web_form": 2, "direct_admin": 1}
    assert data["cancellation_rate"] == "33%"
    assert len(data["by_hour"]) == 24
    assert sum(row["orders"] for row in data["by_hour"]) == 3
