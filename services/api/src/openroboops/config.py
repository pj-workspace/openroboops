from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENROBOOPS_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "OpenRoboOps"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./openroboops.db"
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    data_root: Path = Path("./data/episodes")
    seed_simulator: bool = True
    poll_interval_seconds: int = 5
    persist_interval_seconds: int = 30
    episode_scan_interval_seconds: int = 60
    telemetry_retention_days: int = 90
    session_hours: int = 12
    control_lease_seconds: int = 60
    api_prefix: str = "/api/v1"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
