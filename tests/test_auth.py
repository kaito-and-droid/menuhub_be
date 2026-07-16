import uuid

from tests.conftest import auth_headers, register_shop


async def test_register_and_access_protected_route(client):
    tokens = await register_shop(client)
    assert tokens["role"] == "owner"
    resp = await client.get(
        f"/api/shops/{tokens['shop_id']}/menu", headers=auth_headers(tokens)
    )
    assert resp.status_code == 200


async def test_register_duplicate_email(client):
    unique = uuid.uuid4().hex[:8]
    body = {
        "email": f"dup-{unique}@example.com",
        "password": "secret-password",
        "name": "Dup",
        "shop_name": f"Dup Shop {unique}",
    }
    assert (await client.post("/api/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/auth/register", json=body)).status_code == 409


async def test_login_and_bad_password(client):
    unique = uuid.uuid4().hex[:8]
    email = f"login-{unique}@example.com"
    await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "secret-password",
            "name": "L",
            "shop_name": f"Login Shop {unique}",
        },
    )
    ok = await client.post(
        "/api/auth/login", json={"email": email, "password": "secret-password"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post("/api/auth/login", json={"email": email, "password": "wrong-pass"})
    assert bad.status_code == 401


async def test_refresh_flow(client):
    tokens = await register_shop(client)
    resp = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    # An access token must not be usable as a refresh token
    resp = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert resp.status_code == 401


async def test_requires_token(client):
    tokens = await register_shop(client)
    resp = await client.get(f"/api/shops/{tokens['shop_id']}/menu")
    assert resp.status_code == 401

    # Refresh token must not work as an access token
    resp = await client.get(
        f"/api/shops/{tokens['shop_id']}/menu",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert resp.status_code == 401
