from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, BeforeValidator
from typing import Annotated

def parse_cors(v):
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    return v

class Settings(BaseSettings):
    cors_origins: Annotated[list[str], BeforeValidator(parse_cors)]

print(Settings(_env_file=None, cors_origins="http://a, http://b").cors_origins)
