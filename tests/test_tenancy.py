from tests.conftest import auth_headers, register_shop


async def test_cannot_access_other_shop(client):
    shop_a = await register_shop(client, "tenant-a")
    shop_b = await register_shop(client, "tenant-b")
    headers_a = auth_headers(shop_a)

    # Shop A's token against shop B's resources → 403 across all menu routes
    base_b = f"/api/shops/{shop_b['shop_id']}/menu"
    assert (await client.get(base_b, headers=headers_a)).status_code == 403
    assert (
        await client.post(
            f"{base_b}/categories", json={"name": "Sneaky"}, headers=headers_a
        )
    ).status_code == 403
    assert (
        await client.post(
            f"{base_b}/items", json={"name": "Sneaky", "price": 1}, headers=headers_a
        )
    ).status_code == 403


async def test_cannot_mutate_other_shops_items_via_own_shop_path(client):
    shop_a = await register_shop(client, "cross-a")
    shop_b = await register_shop(client, "cross-b")

    item_b = (
        await client.post(
            f"/api/shops/{shop_b['shop_id']}/menu/items",
            json={"name": "B Item", "price": 20000},
            headers=auth_headers(shop_b),
        )
    ).json()

    # A uses their own shop path but B's item id → 404, never a cross-tenant hit
    base_a = f"/api/shops/{shop_a['shop_id']}/menu"
    resp = await client.patch(
        f"{base_a}/items/{item_b['id']}", json={"price": 1}, headers=auth_headers(shop_a)
    )
    assert resp.status_code == 404
    resp = await client.delete(f"{base_a}/items/{item_b['id']}", headers=auth_headers(shop_a))
    assert resp.status_code == 404
