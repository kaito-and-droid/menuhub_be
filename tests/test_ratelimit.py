from tests.test_orders import order_body, setup_shop


async def test_public_order_rate_limit(client):
    tokens, headers, ingredient, item = await setup_shop(client, "ratelim")
    url = f"/api/public/shops/{tokens['shop_slug']}/orders"

    for i in range(10):
        resp = await client.post(url, json=order_body(item["id"], quantity=1, phone=f"09000000{i:02d}"))
        assert resp.status_code == 201, f"request {i + 1}: {resp.text}"

    resp = await client.post(url, json=order_body(item["id"], quantity=1, phone="0900000099"))
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"
