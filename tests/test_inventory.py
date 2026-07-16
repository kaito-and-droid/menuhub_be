from tests.conftest import auth_headers, register_shop


async def test_ingredient_crud_and_low_stock(client):
    tokens = await register_shop(client, "inv")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/ingredients"

    resp = await client.post(
        base,
        json={"name": "Arabica Beans", "unit": "g", "current_quantity": 1000, "reorder_level": 500},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    ingredient = resp.json()
    assert ingredient["low_stock"] is False

    resp = await client.patch(
        f"{base}/{ingredient['id']}", json={"reorder_level": 1200}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["low_stock"] is True

    listed = (await client.get(base, headers=headers)).json()
    assert [i["name"] for i in listed] == ["Arabica Beans"]


async def test_purchase_log_increments_stock(client):
    tokens = await register_shop(client, "purch")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/ingredients"

    ingredient = (
        await client.post(
            base,
            json={"name": "Milk", "unit": "ml", "current_quantity": 500, "reorder_level": 200},
            headers=headers,
        )
    ).json()

    resp = await client.post(
        f"{base}/logs",
        json={
            "ingredient_id": ingredient["id"],
            "quantity": 1000,
            "cost": 200000,
            "supplier_name": "Vinamilk",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["ingredient_name"] == "Milk"

    listed = (await client.get(base, headers=headers)).json()
    assert listed[0]["current_quantity"] == 1500
    assert listed[0]["last_purchase_price"] == 200  # 200000 / 1000
    assert listed[0]["supplier_name"] == "Vinamilk"

    logs = (await client.get(f"{base}/logs", headers=headers)).json()
    assert len(logs) == 1
    assert logs[0]["quantity"] == 1000


async def test_inventory_tenancy(client):
    shop_a = await register_shop(client, "inv-a")
    shop_b = await register_shop(client, "inv-b")
    base_b = f"/api/shops/{shop_b['shop_id']}/ingredients"

    assert (await client.get(base_b, headers=auth_headers(shop_a))).status_code == 403
    assert (
        await client.post(
            base_b, json={"name": "X", "unit": "g"}, headers=auth_headers(shop_a)
        )
    ).status_code == 403
