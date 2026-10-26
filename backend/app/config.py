from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    @property
    def resolved_database_path(self) -> Path:
        """Resolve relative paths from the repository, independent of the launch directory."""
        path = self.database_path.expanduser()
        return (path if path.is_absolute() else ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
