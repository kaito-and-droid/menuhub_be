import uuid
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db import get_db
from app.models import Shop, User

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_shop(
    shop_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    db: DbSession,
) -> Shop:
    """Multi-tenancy guard: the authenticated user must belong to the shop in the path."""
    if user.shop_id != shop_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this shop")
    shop = await db.get(Shop, shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shop not found")
    return shop


CurrentShop = Annotated[Shop, Depends(get_current_shop)]
