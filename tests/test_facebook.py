import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from tests.conftest import auth_headers
from tests.test_orders import order_body, setup_shop


@pytest.fixture
def graph_calls(monkeypatch):
    calls = []

    async def fake_graph_post(path, payload, token):
        calls.append({"path": path, "payload": payload, "token": token})

    monkeypatch.setattr("app.services.messenger._graph_post", fake_graph_post)
    return calls


async def connect_facebook(client, tokens, page_id):
    resp = await client.patch(
        f"/api/shops/{tokens['shop_id']}/settings",
        json={"facebook_page_id": page_id, "facebook_page_access_token": "page-token"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200


async def test_webhook_verification(client):
    ok = await client.get(
        "/webhooks/facebook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": get_settings().facebook_verify_token,
            "hub.challenge": "42",
        },
    )
    assert ok.status_code == 200
    assert ok.text == "42"

    bad = await client.get(
        "/webhooks/facebook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
    )
    assert bad.status_code == 403


async def test_webhook_signature_enforced(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "facebook_app_secret", "test-secret")
    body = json.dumps({"object": "page", "entry": []}).encode()
    good_sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

    ok = await client.post(
        "/webhooks/facebook", content=body,
        headers={"X-Hub-Signature-256": good_sig, "Content-Type": "application/json"},
    )
    assert ok.status_code == 200

    bad = await client.post(
        "/webhooks/facebook", content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
    )
    assert bad.status_code == 403

    missing = await client.post(
        "/webhooks/facebook", content=body, headers={"Content-Type": "application/json"}
    )
    assert missing.status_code == 403


def page_event(page_id, messaging):
    return {"object": "page", "entry": [{"id": page_id, "messaging": [messaging]}]}


async def test_referral_links_order_and_notifies_on_status(client, graph_calls):
    tokens, headers, ingredient, item = await setup_shop(client, "fb")
    page_id = f"page-{uuid.uuid4().hex[:8]}"
    await connect_facebook(client, tokens, page_id)

    order = (
        await client.post(
            f"/api/public/shops/{tokens['shop_slug']}/orders", json=order_body(item["id"])
        )
    ).json()

    # Customer taps m.me/<page>?ref=order:<id>
    resp = await client.post(
        "/webhooks/facebook",
        json=page_event(
            page_id,
            {"sender": {"id": "PSID-1"}, "referral": {"ref": f"order:{order['id']}"}},
        ),
    )
    assert resp.status_code == 200
    assert graph_calls[-1]["payload"]["recipient"] == {"id": "PSID-1"}
    assert order["order_number"] in graph_calls[-1]["payload"]["message"]["text"]

    from app.db import get_sessionmaker
    from app.models import Order

    async with get_sessionmaker()() as session:
        stored = await session.scalar(
            select(Order).where(Order.id == uuid.UUID(order["id"]))
        )
        assert stored.messenger_user_id == "PSID-1"

    # Status transitions now push Messenger notifications
    before = len(graph_calls)
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/orders/{order['id']}",
        json={"status": "preparing"},
        headers=headers,
    )
    assert len(graph_calls) == before + 1
    assert "prepared" in graph_calls[-1]["payload"]["message"]["text"]

    # An order without a messenger link stays silent
    silent = (
        await client.post(
            f"/api/public/shops/{tokens['shop_slug']}/orders",
            json=order_body(item["id"], phone="0988888888"),
        )
    ).json()
    before = len(graph_calls)
    await client.patch(
        f"/api/shops/{tokens['shop_id']}/orders/{silent['id']}",
        json={"status": "preparing"},
        headers=headers,
    )
    assert len(graph_calls) == before


async def test_message_replies(client, graph_calls):
    tokens, headers, ingredient, item = await setup_shop(client, "fbmsg")
    page_id = f"page-{uuid.uuid4().hex[:8]}"
    await connect_facebook(client, tokens, page_id)
    order = (
        await client.post(
            f"/api/public/shops/{tokens['shop_slug']}/orders", json=order_body(item["id"])
        )
    ).json()

    # Order-number lookup
    await client.post(
        "/webhooks/facebook",
        json=page_event(
            page_id,
            {"sender": {"id": "PSID-2"}, "message": {"text": f"status {order['order_number']}?"}},
        ),
    )
    text = graph_calls[-1]["payload"]["message"]["text"]
    assert order["order_number"] in text
    assert "pending" in text

    # Anything else → greeting with the order link
    await client.post(
        "/webhooks/facebook",
        json=page_event(page_id, {"sender": {"id": "PSID-2"}, "message": {"text": "hello"}}),
    )
    assert f"/order/{tokens['shop_slug']}" in graph_calls[-1]["payload"]["message"]["text"]


async def test_webhook_unknown_page_ignored(client, graph_calls):
    resp = await client.post(
        "/webhooks/facebook",
        json=page_event("no-such-page", {"sender": {"id": "X"}, "message": {"text": "hi"}}),
    )
    assert resp.status_code == 200
    assert graph_calls == []
