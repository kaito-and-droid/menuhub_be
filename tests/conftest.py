import os
import tempfile
import uuid
from pathlib import Path

# Environment must be set before any app module is imported (settings/engine are cached).
_TEST_DB = "menuhub_test"
_PG_SERVER = "postgresql://menuhub:menuhub@localhost:5432"
os.environ["DATABASE_URL"] = f"postgresql+asyncpg://menuhub:menuhub@localhost:5432/{_TEST_DB}"

_keys_dir = Path(tempfile.mkdtemp(prefix="menuhub-test-keys-"))
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
(_keys_dir / "jwt_private.pem").write_bytes(
    _key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)
(_keys_dir / "jwt_public.pem").write_bytes(
    _key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
)
os.environ["JWT_PRIVATE_KEY_PATH"] = str(_keys_dir / "jwt_private.pem")
os.environ["JWT_PUBLIC_KEY_PATH"] = str(_keys_dir / "jwt_public.pem")

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    conn = await asyncpg.connect(f"{_PG_SERVER}/postgres")
    await conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
    await conn.execute(f"CREATE DATABASE {_TEST_DB}")
    await conn.close()

    from app.db import get_engine
    from app.models import Base

    engine = get_engine()
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def register_shop(client: httpx.AsyncClient, prefix: str = "shop") -> dict:
    """Register a fresh shop+owner; returns the token response payload."""
    unique = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": f"{prefix}-{unique}@example.com",
            "password": "secret-password",
            "name": f"Owner {unique}",
            "shop_name": f"{prefix} {unique}",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
