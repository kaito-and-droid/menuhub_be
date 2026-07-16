import uuid

from sqlalchemy import select

from tests.conftest import auth_headers, register_shop


async def setup_shop(client, prefix="ord"):
    """Shop with one ingredient (1000 g, reorder 500) and a Cappuccino using 18 g each."""
    tokens = await register_shop(client, prefix)
    headers = auth_headers(tokens)
    shop_id = tokens["shop_id"]
    ingredient = (
        await client.post(
            f"/api/shops/{shop_id}/ingredients",
            json={"name": "Coffee Beans", "unit": "g", "current_quantity": 1000, "reorder_level": 500},
            headers=headers,
        )
    ).json()
    item = (
        await client.post(
            f"/api/shops/{shop_id}/menu/items",
            json={
                "name": "Cappuccino",
                "price": 55000,
                "cost": 15000,
                "ingredients": [
                    {"ingredient_id": ingredient["id"], "quantity": 18, "unit": "g"}
                ],
            },
            headers=headers,
        )
    ).json()
    return tokens, headers, ingredient, item


def order_body(item_id, quantity=2, phone="0932123456", payment="cash"):
    return {
        "customer": {"name": "Minh", "phone": phone, "email": "minh@example.com"},
        "items": [{"menu_item_id": item_id, "quantity": quantity, "notes": "No sugar"}],
        "delivery_type": "pickup",
        "payment_method": payment,
    }


async def current_stock(client, tokens, headers) -> float:
    listed = (
        await client.get(f"/api/shops/{tokens['shop_id']}/ingredients", headers=headers)
    ).json()
    return listed[0]["current_quantity"]


async def test_public_order_creates_everything(client):
    tokens, headers, ingredient, item = await setup_shop(client, "pub-ord")
    slug = tokens["shop_slug"]

    resp = await client.post(
        f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=2)
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["order_number"] == "#001"
    assert created["total_amount"] == 110000  # server-side pricing
    assert created["status"] == "pending"

    # Stock decremented: 1000 - 2×18
    assert await current_stock(client, tokens, headers) == 964

    # Customer auto-created with stats
    customers = (
        await client.get(f"/api/shops/{tokens['shop_id']}/customers", headers=headers)
    ).json()
    assert len(customers) == 1
    assert customers[0]["phone"] == "0932123456"
    assert customers[0]["order_count"] == 1
    assert customers[0]["total_spent"] == 110000

    # Second order, same phone → same customer, updated stats, next number
    resp = await client.post(
        f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=1)
    )
    assert resp.json()["order_number"] == "#002"
    customers = (
        await client.get(f"/api/shops/{tokens['shop_id']}/customers", headers=headers)
    ).json()
    assert len(customers) == 1
    assert customers[0]["order_count"] == 2
    assert customers[0]["total_spent"] == 165000

    # Admin list embeds customer + item names
    orders = (
        await client.get(f"/api/shops/{tokens['shop_id']}/orders", headers=headers)
    ).json()
    assert len(orders) == 2
    assert orders[0]["customer"]["name"] == "Minh"
    assert orders[0]["items"][0]["name"] == "Cappuccino"
    assert orders[0]["source"] == "web_form"


async def test_order_validation_errors(client):
    tokens, headers, ingredient, item = await setup_shop(client, "val-ord")
    slug = tokens["shop_slug"]

    # Unknown item
    resp = await client.post(
        f"/api/public/shops/{slug}/orders", json=order_body(str(uuid.uuid4()))
    )
    assert resp.status_code == 400

    # Unavailable item
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/menu/items/{item['id']}",
        json={"is_available": False},
        headers=headers,
    )
    resp = await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"]))
    assert resp.status_code == 400
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/menu/items/{item['id']}",
        json={"is_available": True},
        headers=headers,
    )

    # Payment method not enabled (default shop config disables stripe)
    resp = await client.post(
        f"/api/public/shops/{slug}/orders", json=order_body(item["id"], payment="stripe")
    )
    assert resp.status_code == 400

    # Item belonging to another shop
    other_tokens, other_headers, _, other_item = await setup_shop(client, "val-other")
    resp = await client.post(
        f"/api/public/shops/{slug}/orders", json=order_body(other_item["id"])
    )
    assert resp.status_code == 400


async def test_status_transitions_and_completion_side_effects(client):
    tokens, headers, ingredient, item = await setup_shop(client, "tr-ord")
    slug = tokens["shop_slug"]
    base = f"/api/shops/{tokens['shop_id']}/orders"

    order = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"]))
    ).json()

    # Invalid jump
    resp = await client.patch(
        f"{base}/{order['id']}", json={"status": "completed"}, headers=headers
    )
    assert resp.status_code == 409

    for next_status in ("preparing", "ready", "completed"):
        resp = await client.patch(
            f"{base}/{order['id']}", json={"status": next_status}, headers=headers
        )
        assert resp.status_code == 200, resp.text

    final = resp.json()
    assert final["completed_at"] is not None
    assert final["payment_status"] == "completed"

    # Completion recorded a transaction; transitions were audited
    from app.db import get_sessionmaker
    from app.models import AuditLog, Transaction

    async with get_sessionmaker()() as session:
        txs = (
            await session.scalars(
                select(Transaction).where(Transaction.order_id == uuid.UUID(order["id"]))
            )
        ).all()
        assert len(txs) == 1
        assert int(txs[0].amount) == 110000
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.entity_id == uuid.UUID(order["id"]))
            )
        ).all()
        # 1 creation + 3 status transitions
        assert len(audits) == 4
        assert [a.action for a in audits].count("created") == 1
        assert [a.action for a in audits].count("updated") == 3

    # Terminal state: no further transitions
    resp = await client.patch(
        f"{base}/{order['id']}", json={"status": "cancelled"}, headers=headers
    )
    assert resp.status_code == 409


async def test_cancel_restores_stock_and_delete_rules(client):
    tokens, headers, ingredient, item = await setup_shop(client, "cx-ord")
    slug = tokens["shop_slug"]
    base = f"/api/shops/{tokens['shop_id']}/orders"

    order = (
        await client.post(
            f"/api/public/shops/{slug}/orders", json=order_body(item["id"], quantity=1)
        )
    ).json()
    assert await current_stock(client, tokens, headers) == 982

    # Cannot delete a pending order
    resp = await client.delete(f"{base}/{order['id']}", headers=headers)
    assert resp.status_code == 409

    resp = await client.patch(
        f"{base}/{order['id']}", json={"status": "cancelled"}, headers=headers
    )
    assert resp.status_code == 200
    assert await current_stock(client, tokens, headers) == 1000

    resp = await client.delete(f"{base}/{order['id']}", headers=headers)
    assert resp.status_code == 204


async def test_admin_list_filters_and_manual_entry(client):
    tokens, headers, ingredient, item = await setup_shop(client, "adm-ord")
    base = f"/api/shops/{tokens['shop_id']}/orders"

    # Manual admin entry
    resp = await client.post(base, json=order_body(item["id"], phone="0900000001"), headers=headers)
    assert resp.status_code == 201, resp.text
    first = resp.json()
    assert first["source"] == "direct_admin"

    await client.post(base, json=order_body(item["id"], phone="0900000002"), headers=headers)
    await client.patch(f"{base}/{first['id']}", json={"status": "preparing"}, headers=headers)

    pending = (await client.get(f"{base}?status=pending", headers=headers)).json()
    assert len(pending) == 1
    preparing = (await client.get(f"{base}?status=preparing", headers=headers)).json()
    assert [o["id"] for o in preparing] == [first["id"]]


async def test_public_status_hides_pii(client):
    tokens, headers, ingredient, item = await setup_shop(client, "st-ord")
    slug = tokens["shop_slug"]
    order = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"]))
    ).json()

    resp = await client.get(f"/api/public/shops/{slug}/status/{order['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"] == order["order_number"]
    assert data["status"] == "pending"
    assert "customer" not in data
    assert "items" not in data

    # Order from another shop's slug → 404
    other = await register_shop(client, "st-other")
    resp = await client.get(f"/api/public/shops/{other['shop_slug']}/status/{order['id']}")
    assert resp.status_code == 404


async def test_orders_tenancy(client):
    shop_a = await register_shop(client, "ten-ord-a")
    shop_b = await register_shop(client, "ten-ord-b")
    for path in ("orders", "customers"):
        resp = await client.get(
            f"/api/shops/{shop_b['shop_id']}/{path}", headers=auth_headers(shop_a)
        )
        assert resp.status_code == 403


async def test_estimated_ready_time_follows_prep_minutes(client):
    from datetime import datetime, timedelta, timezone

    tokens, headers, ingredient, item = await setup_shop(client, "eta")
    slug = tokens["shop_slug"]

    def minutes_from_now(iso: str) -> float:
        eta = datetime.fromisoformat(iso)
        return (eta - datetime.now(timezone.utc)) / timedelta(minutes=1)

    order = (
        await client.post(f"/api/public/shops/{slug}/orders", json=order_body(item["id"]))
    ).json()
    assert 13 < minutes_from_now(order["estimated_ready_at"]) <= 15

    # Owner raises prep time; new orders reflect it
    resp = await client.patch(
        f"/api/shops/{tokens['shop_id']}/settings", json={"prep_minutes": 40}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["prep_minutes"] == 40

    order2 = (
        await client.post(
            f"/api/public/shops/{slug}/orders", json=order_body(item["id"], phone="0966666666")
        )
    ).json()
    assert 38 < minutes_from_now(order2["estimated_ready_at"]) <= 40

    status = (await client.get(f"/api/public/shops/{slug}/status/{order2['id']}")).json()
    assert status["estimated_ready_at"] == order2["estimated_ready_at"]
