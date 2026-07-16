from tests.conftest import auth_headers, register_shop


async def test_settings_roundtrip_and_token_privacy(client):
    tokens = await register_shop(client, "set")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/settings"

    data = (await client.get(base, headers=headers)).json()
    assert data["payment_methods"] == {"cash": True, "bank_transfer": True, "stripe": False}
    assert data["facebook_connected"] is False
    assert "facebook_page_access_token" not in data
    assert "facebook_app_access_token" not in data

    resp = await client.patch(
        base,
        json={
            "shop_name": "New Name",
            "phone": "0281234567",
            "payment_methods": {"cash": True, "bank_transfer": False, "stripe": False},
            "facebook_page_id": "1234567890",
            "facebook_page_access_token": "EAAG-super-secret",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["shop_name"] == "New Name"
    assert data["payment_methods"]["bank_transfer"] is False
    assert data["facebook_page_id"] == "1234567890"
    assert data["facebook_connected"] is True
    assert "EAAG-super-secret" not in resp.text


async def test_settings_payment_validation(client):
    tokens = await register_shop(client, "setpay")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/settings"

    resp = await client.patch(
        base,
        json={"payment_methods": {"cash": False, "bank_transfer": False, "stripe": False}},
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await client.patch(
        base, json={"payment_methods": {"paypal": True}}, headers=headers
    )
    assert resp.status_code == 422


async def test_settings_tenancy(client):
    shop_a = await register_shop(client, "set-a")
    shop_b = await register_shop(client, "set-b")
    resp = await client.get(
        f"/api/shops/{shop_b['shop_id']}/settings", headers=auth_headers(shop_a)
    )
    assert resp.status_code == 403
