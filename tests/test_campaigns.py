import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from tests.conftest import auth_headers, register_shop
from tests.test_orders import order_body, setup_shop


def campaign_body(**overrides):
    body = {
        "title": "10% off everything",
        "description": "Grand opening week",
        "discount_type": "percent",
        "discount_value": 10,
        "starts_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "is_active": True,
    }
    body.update(overrides)
    return body


async def create_campaign(client, tokens, **overrides):
    resp = await client.post(
        f"/api/shops/{tokens['shop_id']}/campaigns",
        json=campaign_body(**overrides),
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_campaign_crud_and_validation(client):
    tokens = await register_shop(client, "camp")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/campaigns"

    campaign = await create_campaign(client, tokens)
    assert campaign["status"] == "running"
    assert campaign["discount_label"] == "-10%"

    resp = await client.patch(
        f"{base}/{campaign['id']}", json={"is_active": False}, headers=headers
    )
    assert resp.json()["status"] == "disabled"

    # Validation: percent out of range
    resp = await client.post(base, json=campaign_body(discount_value=150), headers=headers)
    assert resp.status_code == 422
    # ends before starts
    resp = await client.post(
        base,
        json=campaign_body(
            ends_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        ),
        headers=headers,
    )
    assert resp.status_code == 422

    # Unreferenced campaign can be deleted
    resp = await client.delete(f"{base}/{campaign['id']}", headers=headers)
    assert resp.status_code == 204

    # Tenancy
    other = await register_shop(client, "camp-other")
    resp = await client.get(base, headers=auth_headers(other))
    assert resp.status_code == 403


async def test_public_menu_lists_only_running_campaigns(client):
    tokens, headers, ingredient, item = await setup_shop(client, "camp-pub")
    slug = tokens["shop_slug"]
    now = datetime.now(timezone.utc)

    running = await create_campaign(client, tokens, title="Running promo")
    await create_campaign(
        client, tokens, title="Scheduled", starts_at=(now + timedelta(days=1)).isoformat()
    )
    await create_campaign(
        client, tokens, title="Expired",
        starts_at=(now - timedelta(days=5)).isoformat(),
        ends_at=(now - timedelta(days=1)).isoformat(),
    )
    await create_campaign(client, tokens, title="Disabled", is_active=False)

    # Campaign mutations invalidate the cached menu, so this read is fresh
    menu = (await client.get(f"/api/public/shops/{slug}/menu")).json()
    assert [c["title"] for c in menu["campaigns"]] == ["Running promo"]
    assert menu["campaigns"][0]["discount_label"] == "-10%"

    # Disabling the running one removes it from the public menu immediately
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/campaigns/{running['id']}",
        json={"is_active": False},
        headers=headers,
    )
    menu = (await client.get(f"/api/public/shops/{slug}/menu")).json()
    assert menu["campaigns"] == []


async def test_percent_discount_applied_to_order(client):
    tokens, headers, ingredient, item = await setup_shop(client, "camp-pct")
    slug = tokens["shop_slug"]
    campaign = await create_campaign(client, tokens)

    order = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=2))
    ).json()
    assert order["subtotal"] == 110000
    assert order["discount_amount"] == 11000
    assert order["total_amount"] == 99000
    assert order["campaign_title"] == "10% off everything"

    # Customer stats use the discounted total
    customers = (
        await client.get(f"/api/shops/{tokens['shop_id']}/customers", headers=headers)
    ).json()
    assert customers[0]["total_spent"] == 99000

    # Admin order view carries the discount + campaign id persisted
    admin_order = (
        await client.get(f"/api/shops/{tokens['shop_id']}/orders/{order['id']}", headers=headers)
    ).json()
    assert admin_order["discount_amount"] == 11000
    from app.db import get_sessionmaker
    from app.models import Order

    async with get_sessionmaker()() as session:
        stored = await session.scalar(select(Order).where(Order.id == uuid.UUID(order["id"])))
        assert str(stored.campaign_id) == campaign["id"]

    # Campaign with orders attached cannot be hard-deleted
    resp = await client.delete(
        f"/api/shops/{tokens['shop_id']}/campaigns/{campaign['id']}", headers=headers
    )
    assert resp.status_code == 400


async def test_fixed_discount_with_minimum(client):
    tokens, headers, ingredient, item = await setup_shop(client, "camp-fix")
    slug = tokens["shop_slug"]
    await create_campaign(
        client, tokens,
        title="20k off from 100k",
        discount_type="fixed",
        discount_value=20000,
        min_order_amount=100000,
    )

    # Below minimum: 1 × 55000 → no discount
    below = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=1))
    ).json()
    assert below["discount_amount"] == 0
    assert below["total_amount"] == 55000
    assert below["campaign_title"] is None

    # Above minimum: 2 × 55000 → −20000
    above = (
        await client.post(
            f"/api/public/shops/{slug}/orders",
            json=order_body(item["id"], quantity=2, phone="0919999999"),
        )
    ).json()
    assert above["discount_amount"] == 20000
    assert above["total_amount"] == 90000


async def test_best_single_discount_wins(client):
    tokens, headers, ingredient, item = await setup_shop(client, "camp-best")
    slug = tokens["shop_slug"]
    await create_campaign(client, tokens, title="Small", discount_type="percent", discount_value=5)
    await create_campaign(
        client, tokens, title="Big", discount_type="fixed", discount_value=15000
    )

    # 2 × 55000 = 110000 → 5% = 5500 vs fixed 15000 → Big wins, no stacking
    order = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=2))
    ).json()
    assert order["discount_amount"] == 15000
    assert order["campaign_title"] == "Big"


async def test_informational_campaign_and_completion_totals(client):
    tokens, headers, ingredient, item = await setup_shop(client, "camp-info")
    slug = tokens["shop_slug"]
    await create_campaign(
        client, tokens, title="New summer menu!", discount_type="none", discount_value=None
    )
    await create_campaign(client, tokens, title="10% promo")

    order = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=2))
    ).json()
    assert order["total_amount"] == 99000  # info campaign didn't affect the math

    base = f"/api/shops/{tokens['shop_id']}/orders"
    for next_status in ("preparing", "ready", "completed"):
        await client.patch(f"{base}/{order['id']}", json={"status": next_status}, headers=headers)

    # Revenue transaction equals the discounted total
    from app.db import get_sessionmaker
    from app.models import Transaction

    async with get_sessionmaker()() as session:
        tx = await session.scalar(
            select(Transaction).where(Transaction.order_id == uuid.UUID(order["id"]))
        )
        assert int(tx.amount) == 99000
