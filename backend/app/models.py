"""Storage contracts. Missing facts stay null; collection/extraction comes later."""

from datetime import date as Date
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Category = Literal["hackathon", "BCC", "BPC", "uncertain"]
SourceStatus = Literal["not_checked", "ok", "partial", "failed", "not_connected"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Money(Model):
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    basis: Literal["person", "team", "unknown"] = "unknown"
    raw_text: str


class Prize(Model):
    description: str
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    is_total_pool: bool | None = None


class TimelineEntry(Model):
    kind: Literal["registration", "submission", "event", "final", "other"]
    label: str | None = None
    raw_text: str = Field(min_length=1)
    date: Date | None = None
    at: AwareDatetime | None = None
    timezone: str | None = None
    needs_review: bool = True


class CompetitionData(Model):
    name: str = Field(min_length=1, max_length=300)
    category: Category = "uncertain"
    organizer: str | None = None
    edition: str | None = None
    summary: str | None = None
    eligibility: str | None = None
    team_min: int | None = Field(default=None, ge=1)
    team_max: int | None = Field(default=None, ge=1)
    team_raw: str | None = None
    format: Literal["online", "offline", "hybrid", "unknown"] = "unknown"
    location: str | None = None
    country: str | None = None
    fees: list[Money] = Field(default_factory=list)
    prizes: list[Prize] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    source_url: HttpUrl
    official_url: HttpUrl | None = None
    registration_url: HttpUrl | None = None
    guidebook_url: HttpUrl | None = None
    relevance_status: Literal["unreviewed", "relevant", "needs_review", "excluded"] = "unreviewed"
    registration_status: Literal["unknown", "upcoming", "open", "closed"] = "unknown"
    warnings: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_team_range(self) -> "CompetitionData":
        if self.team_min is not None and self.team_max is not None and self.team_min > self.team_max:
            raise ValueError("Jumlah minimum anggota tidak boleh melebihi maksimum.")
        return self


class CompetitionRecord(Model):
    id: int
    dedup_key: str | None
    data: CompetitionData
    version: int
    first_seen_at: AwareDatetime
    last_checked_at: AwareDatetime
    updated_at: AwareDatetime


class SourceData(Model):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["website", "rss", "instagram"]
    url: HttpUrl
    adapter: str = Field(min_length=1, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SourceRecord(SourceData):
    id: int
    status: SourceStatus
    last_checked_at: AwareDatetime | None
    last_success_at: AwareDatetime | None
    last_error: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class EvidenceData(Model):
    source_id: int | None = None
    url: HttpUrl
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_text: str
    # Map field paths (e.g. timeline.0.date, fees.0.amount) to their literal source excerpts/values.
    field_values: dict[str, Any] = Field(default_factory=dict)
    fetched_at: AwareDatetime


class Preferences(Model):
    categories: list[Literal["hackathon", "BCC", "BPC"]] = Field(default_factory=lambda: ["hackathon", "BCC", "BPC"], min_length=1)
    country: Literal["ID"] = "ID"
    education_level: Literal["university", "any"] = "university"
    include_unknown_eligibility: bool = True
    hide_closed: bool = True
    discovery_enabled: bool = False

    @field_validator("categories")
    @classmethod
    def unique_categories(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
