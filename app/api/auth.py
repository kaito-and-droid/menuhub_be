import re
import uuid

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import DbSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import Shop, User, UserRole
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "shop"


def _token_response(user: User, shop: Shop) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, shop.id, user.role.value),
        refresh_token=create_refresh_token(user.id, shop.id, user.role.value),
        shop_id=shop.id,
        shop_slug=shop.slug,
        user_name=user.name,
        role=user.role.value,
        currency=shop.currency,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def register(body: RegisterRequest, db: DbSession) -> TokenResponse:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    slug = body.slug or _slugify(body.shop_name)
    if await db.scalar(select(Shop).where(Shop.slug == slug)) is not None:
        if body.slug is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Slug already taken")
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    shop = Shop(shop_name=body.shop_name, slug=slug, email=body.email)
    db.add(shop)
    await db.flush()
    user = User(
        shop_id=shop.id,
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=UserRole.owner,
    )
    db.add(user)
    await db.flush()
    shop.owner_id = user.id
    await db.commit()
    return _token_response(user, shop)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    shop = await db.get(Shop, user.shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Shop is inactive")
    return _token_response(user, shop)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    shop = await db.get(Shop, user.shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Shop is inactive")
    return _token_response(user, shop)
