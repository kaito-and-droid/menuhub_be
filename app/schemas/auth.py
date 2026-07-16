import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    shop_name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    shop_id: uuid.UUID
    shop_slug: str
    user_name: str
    role: str
    currency: str = "VND"
