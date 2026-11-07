from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Lomba Radar"
    app_env: str = "development"
    database_path: Path = Path("data/lomba-radar.db")
    worker_lease_seconds: int = Field(default=90, ge=30, le=3600)
    worker_poll_seconds: float = Field(default=1, ge=0.1, le=30)
    scheduler_poll_seconds: float = Field(default=5, ge=1, le=30)
    brave_api_key: SecretStr = SecretStr("")
    discovery_provider_enabled: bool = False
    apify_token: SecretStr = SecretStr("")
    instagram_provider_enabled: bool = False
    instagram_posts_limit: int = Field(default=5, ge=1, le=20)
    apify_max_charge_usd: float = Field(default=0.05, gt=0, le=1)
    ocr_enabled: bool = False
    tesseract_command: str = "tesseract"
    ocr_language: str = Field(default="eng", pattern=r"^[A-Za-z_+]{1,30}$")
    access_username: str = ""
    access_password: SecretStr = SecretStr("")
    api_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000"

    @property
    def resolved_database_path(self) -> Path:
        """Resolve relative paths from the repository, independent of the launch directory."""
        path = self.database_path.expanduser()
        return (path if path.is_absolute() else ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
