import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "RS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


@lru_cache
def _private_key() -> str:
    settings = get_settings()
    if settings.jwt_private_key:
        # Some env systems might replace newlines with literal '\n', so we unescape it if needed.
        return settings.jwt_private_key.replace("\\n", "\n")
    return settings.jwt_private_key_path.read_text()


@lru_cache
def _public_key() -> str:
    settings = get_settings()
    if settings.jwt_public_key:
        return settings.jwt_public_key.replace("\\n", "\n")
    return settings.jwt_public_key_path.read_text()


def _create_token(
    user_id: uuid.UUID, shop_id: uuid.UUID, role: str, token_type: str, expires: timedelta
) -> str:
    payload = {
        "sub": str(user_id),
        "shop_id": str(shop_id),
        "role": role,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires,
    }
    return jwt.encode(payload, _private_key(), algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID, shop_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    return _create_token(
        user_id, shop_id, role, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: uuid.UUID, shop_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    return _create_token(
        user_id, shop_id, role, "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, _public_key(), algorithms=[ALGORITHM])
