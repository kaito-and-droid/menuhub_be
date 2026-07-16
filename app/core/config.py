from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://menuhub:menuhub@localhost:5432/menuhub"
    redis_url: str = "redis://localhost:6379/0"
    jwt_private_key_path: Path = Path("keys/jwt_private.pem")
    jwt_public_key_path: Path = Path("keys/jwt_public.pem")
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    cors_origins: list[str] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"

    # Facebook integration (empty app secret disables webhook signature checks — dev only)
    facebook_app_secret: str = ""
    facebook_verify_token: str = "menuhub-verify"
    facebook_graph_url: str = "https://graph.facebook.com/v18.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
