from functools import lru_cache
from pathlib import Path
from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, field_validator

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
    brave_cost_per_request_usd: Decimal | None = Field(default=None,gt=0,le=10,decimal_places=6,allow_inf_nan=False)

    apify_token: SecretStr = SecretStr("")
    instagram_provider_enabled: bool = False
    instagram_posts_limit: int = Field(default=5, ge=1, le=20)
    apify_max_charge_usd: float = Field(default=0.05, gt=0, le=1)
    ocr_enabled: bool = False
    tesseract_command: str = "tesseract"
    ocr_language: str = Field(default="eng", pattern=r"^[A-Za-z_+]{1,30}$")
    ai_enabled: bool = False
    ai_model: str = Field(default='', max_length=100, pattern=r'^[A-Za-z0-9_.:-]*$')
    ai_model_revision: str = Field(default='1', min_length=1, max_length=100)
    ai_max_requests_per_job: int = Field(default=3, ge=0, le=20)
    ai_timeout_seconds: int = Field(default=45, ge=5, le=90)

    @field_validator('ai_model')
    @classmethod
    def local_model_only(cls,value):
        if 'cloud' in value.lower():
            raise ValueError('Gunakan model Ollama lokal, bukan model cloud.')
        return value
    access_username: str = ""
    access_password: SecretStr = SecretStr("")
    api_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000"

    @field_validator('brave_cost_per_request_usd',mode='before')
    @classmethod
    def optional_brave_estimate(cls,value):
        return None if value=='' else value

    @property
    def resolved_database_path(self) -> Path:
        """Resolve relative paths from the repository, independent of the launch directory."""
        path = self.database_path.expanduser()
        return (path if path.is_absolute() else ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
