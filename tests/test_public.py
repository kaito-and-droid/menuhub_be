from tests.conftest import auth_headers, register_shop


async def test_public_menu_hides_cost_and_unavailable_items(client):
    tokens = await register_shop(client, "public")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/menu"

    category = (
        await client.post(f"{base}/categories", json={"name": "Coffee"}, headers=headers)
    ).json()
    await client.post(
        f"{base}/items",
        json={"category_id": category["id"], "name": "Latte", "price": 45000, "cost": 12000},
        headers=headers,
    )
    await client.post(
        f"{base}/items",
        json={
            "category_id": category["id"],
            "name": "Seasonal Special",
            "price": 99000,
            "cost": 50000,
            "is_available": False,
        },
        headers=headers,
    )

    resp = await client.get(f"/api/public/shops/{tokens['shop_slug']}/menu")
    assert resp.status_code == 200
    menu = resp.json()
    assert menu["shop_name"]

    items = [i for c in menu["categories"] for i in c["items"]]
    names = [i["name"] for i in items]
    assert "Latte" in names
    assert "Seasonal Special" not in names  # unavailable items are hidden

    for item in items:
        assert "cost" not in item
        assert "margin" not in item


async def test_public_menu_unknown_slug(client):
    resp = await client.get("/api/public/shops/does-not-exist/menu")
    assert resp.status_code == 404
