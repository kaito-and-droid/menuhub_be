import asyncio
import json
import uuid

from tests.conftest import register_shop
from tests.test_orders import order_body, setup_shop

# NOTE: httpx's ASGITransport buffers entire responses, so an infinite SSE body
# can never be consumed through the test client. These tests exercise the
# pub/sub generator and the endpoint's response object directly; the live HTTP
# stream is covered by the milestone's curl verification.


async def test_pubsub_delivers_order_events(client):
    tokens, headers, ingredient, item = await setup_shop(client, "sse")
    from app.core.events import subscribe_order_events

    shop_id = uuid.UUID(tokens["shop_id"])
    events = subscribe_order_events(shop_id)
    ready = await asyncio.wait_for(anext(events), timeout=10)
    assert ready is None  # subscription active — publishes can no longer be missed

    placed = await client.post(
        f"/api/public/shops/{tokens['shop_slug']}/orders", json=order_body(item["id"])
    )
    assert placed.status_code == 201

    async def next_event():
        while True:
            data = await anext(events)
            if data is not None:
                return json.loads(data)

    event = await asyncio.wait_for(next_event(), timeout=10)
    await events.aclose()
    assert event["type"] == "created"
    assert event["order_number"] == placed.json()["order_number"]
    assert event["status"] == "pending"


async def test_stream_endpoint_formats_sse_frames(client):
    tokens = await register_shop(client, "sse-fmt")
    from app.api.orders import stream_orders
    from app.core.events import publish_order_event

    shop_id = uuid.UUID(tokens["shop_id"])
    response = await stream_orders(shop_id, tokens["access_token"])
    assert response.media_type == "text/event-stream"

    frames = response.body_iterator
    first = await asyncio.wait_for(anext(frames), timeout=10)
    assert first == ": ping\n\n"  # subscription-active keepalive

    await publish_order_event(
        shop_id,
        {"type": "status_changed", "order_id": "x", "order_number": "#009", "status": "ready"},
    )

    # Skip keepalive pings (redis-py may emit an early None when it swallows the
    # subscribe-confirmation frame), exactly as a real EventSource ignores comments.
    async def next_data_frame():
        async for frame in frames:
            if frame.startswith("data: "):
                return frame

    frame = await asyncio.wait_for(next_data_frame(), timeout=10)
    await frames.aclose()
    assert json.loads(frame.removeprefix("data: ").strip())["order_number"] == "#009"


async def test_sse_auth(client):
    tokens = await register_shop(client, "sse-auth")
    base = f"/api/shops/{tokens['shop_id']}/orders/stream"

    resp = await client.get(f"{base}?token=garbage")
    assert resp.status_code == 401

    # Refresh token is not an access token
    resp = await client.get(f"{base}?token={tokens['refresh_token']}")
    assert resp.status_code == 401

    # Someone else's valid token → 403
    other = await register_shop(client, "sse-other")
    resp = await client.get(f"{base}?token={other['access_token']}")
    assert resp.status_code == 403
