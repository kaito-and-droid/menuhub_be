from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://menuhub:menuhub@localhost:5432/menuhub"
    redis_url: str = "redis://localhost:6379/0"
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_private_key_path: Path = Path("keys/jwt_private.pem")
    jwt_public_key_path: Path = Path("keys/jwt_public.pem")
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    cors_origins: str | list[str] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"

    # Facebook integration (empty app secret disables webhook signature checks — dev only)
    facebook_app_secret: str = ""
    facebook_verify_token: str = "menuhub-verify"
    facebook_graph_url: str = "https://graph.facebook.com/v18.0"

    @field_validator("database_url", mode="before")
    @classmethod
    def assemble_database_url(cls, v: str | Any) -> Any:
        if isinstance(v, str):
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+asyncpg://", 1)
            if v.startswith("postgresql://"):
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
