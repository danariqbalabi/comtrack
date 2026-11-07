"""Validated automation preferences. Stage 1 stores intent; it never dispatches jobs."""
from decimal import Decimal
from typing import Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from .database import Database, utc_now
from .models import Model
from .repository import VersionConflictError, encode


class AutomationSettings(Model):
    enabled: StrictBool = False
    interval_minutes: int = Field(default=360, strict=True, ge=30, le=10080)
    max_sources_per_run: int = Field(default=10, strict=True, ge=1, le=30)
    max_new_sources_per_run: int = Field(default=3, strict=True, ge=0, le=30)
    max_pages_per_source: int = Field(default=5, strict=True, ge=1, le=10)
    max_images_per_post: int = Field(default=3, strict=True, ge=0, le=5)
    allow_paid_providers: StrictBool = False
    provider_daily_request_limit: int = Field(default=0, strict=True, ge=0, le=10000)
    provider_daily_budget_usd: Decimal = Field(default=Decimal('0.00'), ge=0, le=1000, decimal_places=2, allow_inf_nan=False)
    instagram_public_competition_accounts_only: Literal[True] = True

    @field_validator('instagram_public_competition_accounts_only', mode='before')
    @classmethod
    def public_competition_scope(cls, value):
        if value is not True:
            raise ValueError('Instagram dibatasi ke akun publik media lomba dan penyelenggara.')
        return value

    @model_validator(mode='after')
    def consistent_limits(self):
        if self.max_new_sources_per_run > self.max_sources_per_run:
            raise ValueError('Batas sumber baru tidak boleh melebihi batas sumber per pencarian.')
        if self.allow_paid_providers and (self.provider_daily_request_limit == 0 or self.provider_daily_budget_usd == 0):
            raise ValueError('Izin provider berbayar memerlukan batas request dan anggaran harian di atas nol.')
        return self


class AutomationUpdate(Model):
    settings: AutomationSettings
    expected_version: int = Field(strict=True, ge=1)


class AutomationStore:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def snapshot(row):
        return {'settings':AutomationSettings.model_validate_json(row['data_json']),
                'version':row['version'], 'updated_at':row['updated_at']}

    def get(self):
        with self.database.connection() as conn:
            return self.snapshot(conn.execute('SELECT * FROM automation_settings WHERE singleton=1').fetchone())

    def save(self, settings: AutomationSettings, *, expected_version: int):
        with self.database.transaction() as conn:
            changed = conn.execute('''UPDATE automation_settings SET data_json=?,version=version+1,updated_at=?
                WHERE singleton=1 AND version=?''', (encode(settings.model_dump(mode='json')),utc_now(),expected_version))
            if changed.rowcount != 1:
                raise VersionConflictError('Pengaturan sudah berubah di tab/proses lain. Muat ulang sebelum menyimpan.')
            return self.snapshot(conn.execute('SELECT * FROM automation_settings WHERE singleton=1').fetchone())
