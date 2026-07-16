import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import AuditLog
from tests.conftest import auth_headers, register_shop
from tests.test_orders import setup_shop


async def audits_for(entity_id: uuid.UUID) -> list[AuditLog]:
    async with get_sessionmaker()() as session:
        return list(
            await session.scalars(select(AuditLog).where(AuditLog.entity_id == entity_id))
        )


async def test_menu_item_update_audits_changed_fields_only(client):
    tokens, headers, ingredient, item = await setup_shop(client, "aud")
    resp = await client.patch(
        f"/api/shops/{tokens['shop_id']}/menu/items/{item['id']}",
        json={"price": 60000, "name": "Cappuccino"},  # name unchanged
        headers=headers,
    )
    assert resp.status_code == 200

    audits = [a for a in await audits_for(uuid.UUID(item["id"])) if a.action == "updated"]
    assert len(audits) == 1
    assert audits[0].new_value == {"price": 60000}
    assert "name" not in audits[0].new_value
    assert "price" in audits[0].old_value


async def test_settings_audit_masks_token(client):
    tokens = await register_shop(client, "aud-set")
    resp = await client.patch(
        f"/api/shops/{tokens['shop_id']}/settings",
        json={"facebook_page_id": "555", "facebook_page_access_token": "super-secret-token"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200

    audits = await audits_for(uuid.UUID(tokens["shop_id"]))
    settings_audits = [a for a in audits if a.entity_type == "shop_settings"]
    assert len(settings_audits) == 1
    assert settings_audits[0].new_value["facebook_page_access_token"] == "***"
    assert "super-secret-token" not in str(settings_audits[0].new_value)


async def test_ingredient_create_and_purchase_audited(client):
    tokens = await register_shop(client, "aud-ing")
    headers = auth_headers(tokens)
    base = f"/api/shops/{tokens['shop_id']}/ingredients"

    ingredient = (
        await client.post(base, json={"name": "Sugar", "unit": "g"}, headers=headers)
    ).json()
    created = await audits_for(uuid.UUID(ingredient["id"]))
    assert [a.action for a in created] == ["created"]
    assert created[0].new_value["name"] == "Sugar"

    log = (
        await client.post(
            f"{base}/logs",
            json={"ingredient_id": ingredient["id"], "quantity": 100, "cost": 5000},
            headers=headers,
        )
    ).json()
    log_audits = await audits_for(uuid.UUID(log["id"]))
    assert [a.entity_type for a in log_audits] == ["ingredient_log"]
