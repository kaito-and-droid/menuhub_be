import uuid

from tests.conftest import auth_headers, register_shop


async def _create_category(client, tokens, name="Coffee"):
    resp = await client.post(
        f"/api/shops/{tokens['shop_id']}/menu/categories",
        json={"name": name},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_menu_crud_and_margin(client):
    tokens = await register_shop(client, "menu")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/menu"

    category = await _create_category(client, tokens)

    resp = await client.post(
        f"{base}/items",
        json={
            "category_id": category["id"],
            "name": "Cappuccino",
            "description": "Espresso + steamed milk",
            "price": 55000,
            "cost": 15000,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["margin"] == "73%"

    resp = await client.get(base, headers=headers)
    menu = resp.json()
    assert menu["categories"][0]["name"] == "Coffee"
    assert menu["categories"][0]["items"][0]["name"] == "Cappuccino"
    assert menu["categories"][0]["items"][0]["cost"] == 15000

    resp = await client.patch(
        f"{base}/items/{item['id']}",
        json={"price": 60000, "is_available": False},
        headers=headers,
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["price"] == 60000
    assert updated["is_available"] is False
    assert updated["margin"] == "75%"

    resp = await client.delete(f"{base}/items/{item['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.patch(
        f"{base}/items/{item['id']}", json={"price": 1000}, headers=headers
    )
    assert resp.status_code == 404


async def test_item_with_unknown_category_rejected(client):
    tokens = await register_shop(client, "badcat")
    resp = await client.post(
        f"/api/shops/{tokens['shop_id']}/menu/items",
        json={"category_id": str(uuid.uuid4()), "name": "Ghost", "price": 1000},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 400


async def test_delete_category_orphans_items(client):
    tokens = await register_shop(client, "delcat")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/menu"
    category = await _create_category(client, tokens, "Tea")
    item = (
        await client.post(
            f"{base}/items",
            json={"category_id": category["id"], "name": "Oolong", "price": 30000},
            headers=headers,
        )
    ).json()

    resp = await client.delete(f"{base}/categories/{category['id']}", headers=headers)
    assert resp.status_code == 204

    menu = (await client.get(base, headers=headers)).json()
    assert menu["categories"] == []
    assert [i["id"] for i in menu["uncategorized"]] == [item["id"]]


async def test_item_with_unknown_recipe_ingredient_rejected(client):
    tokens = await register_shop(client, "badrecipe")
    resp = await client.post(
        f"/api/shops/{tokens['shop_id']}/menu/items",
        json={
            "name": "Ghost Latte",
            "price": 40000,
            "ingredients": [{"ingredient_id": str(uuid.uuid4()), "quantity": 10, "unit": "g"}],
        },
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 400
    assert "unknown ingredients" in resp.json()["detail"].lower()
