from app.services.paynow import crc16_ccitt
from tests.conftest import auth_headers, register_shop
from tests.test_orders import order_body, setup_shop

UEN = "201403121W"


async def setup_sgd_shop(client, prefix="sg"):
    """SGD shop with PayNow enabled and one S$4.50 item."""
    tokens = await register_shop(client, prefix)
    headers = auth_headers(tokens)
    shop_id = tokens["shop_id"]
    resp = await client.patch(
        f"/api/shops/{shop_id}/settings",
        json={
            "currency": "SGD",
            "paynow_proxy_type": "UEN",
            "paynow_proxy_value": UEN,
            "payment_methods": {"cash": True, "bank_transfer": False, "stripe": False, "paynow": True},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    item = (
        await client.post(
            f"/api/shops/{shop_id}/menu/items",
            json={"name": "Kopi", "price": 4.5, "cost": 1.2},
            headers=headers,
        )
    ).json()
    return tokens, headers, item


async def test_paynow_settings_gating(client):
    tokens = await register_shop(client, "sg-gate")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/settings"

    # Enabling PayNow on a VND shop → rejected
    resp = await client.patch(
        base,
        json={
            "paynow_proxy_type": "UEN",
            "paynow_proxy_value": UEN,
            "payment_methods": {"cash": True, "paynow": True},
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert "SGD" in resp.json()["detail"]

    # SGD but no proxy configured → rejected
    resp = await client.patch(
        base,
        json={"currency": "SGD", "payment_methods": {"cash": True, "paynow": True}},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "proxy" in resp.json()["detail"].lower() or "PayNow" in resp.json()["detail"]

    # Full config in one PATCH → accepted, settings echo the proxy
    resp = await client.patch(
        base,
        json={
            "currency": "SGD",
            "paynow_proxy_type": "MOBILE",
            "paynow_proxy_value": "91234567",
            "payment_methods": {"cash": True, "paynow": True},
        },
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["currency"] == "SGD"
    assert data["paynow_proxy_type"] == "MOBILE"
    assert data["payment_methods"]["paynow"] is True


async def test_paynow_order_generates_valid_qr(client):
    tokens, headers, item = await setup_sgd_shop(client, "sg-qr")
    slug = tokens["shop_slug"]

    # Public menu advertises SGD + enabled methods
    menu = (await client.get(f"/api/public/shops/{slug}/menu")).json()
    assert menu["currency"] == "SGD"
    assert menu["payment_methods"] == ["cash", "paynow"]

    order = (
        await client.post(
            f"/api/public/shops/{slug}/orders",
            json=order_body(item["id"], quantity=2, payment="paynow"),
        )
    ).json()
    assert order["total_amount"] == 9.0  # 2 × S$4.50 — decimals intact
    assert order["currency"] == "SGD"

    qr = order["paynow_qr"]
    assert qr is not None
    assert qr.startswith("000201")
    assert "SG.PAYNOW" in qr
    assert UEN in qr
    assert "54049.00" in qr  # tag 54, len 04, amount 9.00
    reference = order["order_number"].lstrip("#")
    assert f"01{len(reference):02d}{reference}" in qr
    # CRC-16/CCITT-FALSE recomputes to the last four hex chars
    assert qr[-4:] == f"{crc16_ccitt(qr[:-4].encode()):04X}"

    # Cash orders carry no QR
    cash = (
        await client.post(
            f"/api/public/shops/{slug}/orders",
            json=order_body(item["id"], quantity=1, phone="0888888888"),
        )
    ).json()
    assert cash["paynow_qr"] is None


async def test_mark_paid_flow(client):
    tokens, headers, item = await setup_sgd_shop(client, "sg-paid")
    slug = tokens["shop_slug"]
    order = (
        await client.post(
            f"/api/public/shops/{slug}/orders",
            json=order_body(item["id"], payment="paynow"),
        )
    ).json()

    # Status page shows the QR while payment is pending
    status_data = (await client.get(f"/api/public/shops/{slug}/status/{order['id']}")).json()
    assert status_data["payment_status"] == "pending"
    assert status_data["paynow_qr"] is not None

    pay_url = f"/api/shops/{tokens['shop_id']}/orders/{order['id']}/payment"
    resp = await client.patch(pay_url, json={"payment_status": "completed"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payment_status"] == "completed"

    # QR disappears once paid; second confirmation conflicts
    status_data = (await client.get(f"/api/public/shops/{slug}/status/{order['id']}")).json()
    assert status_data["paynow_qr"] is None
    resp = await client.patch(pay_url, json={"payment_status": "completed"}, headers=headers)
    assert resp.status_code == 409

    # Tenancy
    other = await register_shop(client, "sg-paid-other")
    resp = await client.patch(
        pay_url, json={"payment_status": "completed"}, headers=auth_headers(other)
    )
    assert resp.status_code == 403


async def test_postal_code_validation(client):
    # SGD shop: exactly 6 digits
    tokens, headers, item = await setup_sgd_shop(client, "sg-post")
    slug = tokens["shop_slug"]

    def delivery_body(postal=None, phone="0932123456"):
        body = order_body(item["id"], quantity=1, phone=phone)
        body["delivery_type"] = "delivery"
        body["delivery_address"] = "1 Marina Boulevard"
        if postal is not None:
            body["postal_code"] = postal
        return body

    resp = await client.post(f"/api/public/shops/{slug}/orders", json=delivery_body())
    assert resp.status_code == 400
    resp = await client.post(f"/api/public/shops/{slug}/orders", json=delivery_body("12345"))
    assert resp.status_code == 400
    resp = await client.post(f"/api/public/shops/{slug}/orders", json=delivery_body("018989"))
    assert resp.status_code == 201, resp.text

    admin_order = (
        await client.get(
            f"/api/shops/{tokens['shop_id']}/orders/{resp.json()['id']}", headers=headers
        )
    ).json()
    assert admin_order["postal_code"] == "018989"

    # Pickup orders don't need a postal code (covered throughout other suites);
    # VND shops accept 5-6 digits
    vnd_tokens, vnd_headers, ingredient, vnd_item = await setup_shop(client, "vn-post")
    body = order_body(vnd_item["id"], quantity=1)
    body.update({"delivery_type": "delivery", "delivery_address": "1 Nguyen Hue", "postal_code": "70000"})
    resp = await client.post(
        f"/api/public/shops/{vnd_tokens['shop_slug']}/orders", json=body
    )
    assert resp.status_code == 201, resp.text
