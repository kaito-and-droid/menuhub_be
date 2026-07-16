import json

from app.core.cache import menu_key
from app.core.events import get_redis
from tests.conftest import auth_headers
from tests.test_analytics import complete_order
from tests.test_orders import order_body, setup_shop


async def test_public_menu_cached_and_invalidated(client):
    tokens, headers, ingredient, item = await setup_shop(client, "cache-menu")
    slug = tokens["shop_slug"]
    key = menu_key(slug)

    first = await client.get(f"/api/public/shops/{slug}/menu")
    assert first.status_code == 200
    raw = await get_redis().get(key)
    assert raw is not None

    # Prove subsequent reads come from the cache: plant a sentinel
    tampered = json.loads(raw)
    tampered["shop_name"] = "CACHED-SENTINEL"
    await get_redis().set(key, json.dumps(tampered))
    assert (await client.get(f"/api/public/shops/{slug}/menu")).json()["shop_name"] == "CACHED-SENTINEL"

    # A menu mutation invalidates: fresh data immediately
    resp = await client.patch(
        f"/api/shops/{tokens['shop_id']}/menu/items/{item['id']}",
        json={"price": 60000},
        headers=headers,
    )
    assert resp.status_code == 200
    fresh = (await client.get(f"/api/public/shops/{slug}/menu")).json()
    assert fresh["shop_name"] != "CACHED-SENTINEL"
    assert fresh["categories"][0]["items"][0]["price"] == 60000


async def test_settings_change_invalidates_menu_cache(client):
    tokens, headers, ingredient, item = await setup_shop(client, "cache-set")
    slug = tokens["shop_slug"]

    menu = (await client.get(f"/api/public/shops/{slug}/menu")).json()
    assert menu["estimated_wait_minutes"] == 15

    await client.patch(
        f"/api/shops/{tokens['shop_id']}/settings",
        json={"prep_minutes": 25},
        headers=headers,
    )
    menu = (await client.get(f"/api/public/shops/{slug}/menu")).json()
    assert menu["estimated_wait_minutes"] == 25


async def test_revenue_cache_invalidated_on_completion(client):
    tokens, headers, ingredient, item = await setup_shop(client, "cache-rev")
    base = f"/api/shops/{tokens['shop_id']}/analytics/revenue"

    await complete_order(client, tokens, headers, item["id"], "0912000001", qty=2)
    first = (await client.get(base, headers=headers)).json()
    assert first["summary"]["total_revenue"] == 110000

    # Cached now; completing another order must invalidate, not serve stale totals
    await complete_order(client, tokens, headers, item["id"], "0912000002", qty=1)
    second = (await client.get(base, headers=headers)).json()
    assert second["summary"]["total_revenue"] == 165000
