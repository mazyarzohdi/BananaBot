from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    admin_ids: list[int] = []
    database_path: str = "data/bot.db"
    default_lang: str = "fa"
    card_number: str = ""
    card_holder: str = ""
    required_channel: str = ""

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return [int(x) for x in value]
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(x.strip()) for x in value.split(",") if x.strip()]
        return []


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()

