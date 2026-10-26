"""Transactional storage operations; no scraping, fuzzy deduplication, or worker here."""

import json
import sqlite3
from contextlib import nullcontext
from datetime import timezone
from typing import Any, Literal

from .database import Database, utc_now
from .models import CompetitionData, CompetitionRecord, EvidenceData, Preferences, SourceData, SourceRecord


class NotFoundError(LookupError):
    pass


class VersionConflictError(RuntimeError):
    """Another writer has updated this competition since it was read."""


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def competition_record(row: sqlite3.Row) -> CompetitionRecord:
    return CompetitionRecord(
        id=row["id"], dedup_key=row["dedup_key"],
        data=CompetitionData.model_validate_json(row["data_json"]), version=row["version"],
        first_seen_at=row["first_seen_at"], last_checked_at=row["last_checked_at"], updated_at=row["updated_at"],
    )


def source_record(row: sqlite3.Row) -> SourceRecord:
    fields = dict(row)
    fields["config"] = json.loads(fields.pop("config_json"))
    return SourceRecord.model_validate(fields)


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def create_source(self, source: SourceData) -> SourceRecord:
        stamp = utc_now()
        with self.database.transaction() as conn:
            cursor = conn.execute("""INSERT INTO sources
                (name, kind, url, adapter, config_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (source.name, source.kind, str(source.url), source.adapter, encode(source.config),
                 int(source.enabled), stamp, stamp))
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return source_record(row)

    def list_sources(self, *, enabled_only: bool = False) -> list[SourceRecord]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM sources" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY id")
            return [source_record(row) for row in rows]

    def ensure_source(self, source: SourceData) -> SourceRecord:
        """Register only on an explicit collection request; preserve existing enabled/config settings."""
        stamp = utc_now()
        with self.database.transaction() as conn:
            conn.execute("""INSERT INTO sources
                (name, kind, url, adapter, config_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(kind, url) DO NOTHING""",
                (source.name, source.kind, str(source.url), source.adapter, encode(source.config), int(source.enabled), stamp, stamp))
            return source_record(conn.execute("SELECT * FROM sources WHERE kind = ? AND url = ?",
                                              (source.kind, str(source.url))).fetchone())

    def record_source_check(self, source_id: int, *, error: str | None = None) -> None:
        stamp = utc_now()
        with self.database.transaction() as conn:
            cursor = conn.execute("""UPDATE sources SET status = ?, last_checked_at = ?,
                last_success_at = CASE WHEN ? IS NULL THEN ? ELSE last_success_at END,
                last_error = ?, updated_at = ? WHERE id = ?""",
                ("failed" if error else "ok", stamp, error, stamp, error, stamp, source_id))
            if cursor.rowcount != 1:
                raise NotFoundError("Sumber tidak ditemukan.")

    def set_source_enabled(self, source_id: int, enabled: bool) -> None:
        with self.database.transaction() as conn:
            cursor = conn.execute("UPDATE sources SET enabled = ?, updated_at = ? WHERE id = ?",
                                  (int(enabled), utc_now(), source_id))
            if cursor.rowcount != 1:
                raise NotFoundError("Sumber tidak ditemukan.")

    def delete_source(self, source_id: int) -> None:
        # Evidence and logs retain their URLs/text; only the optional monitoring reference becomes null.
        with self.database.transaction() as conn:
            cursor = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            if cursor.rowcount != 1:
                raise NotFoundError("Sumber tidak ditemukan.")

    @staticmethod
    def _insert_evidence(conn: sqlite3.Connection, competition_id: int, evidence: EvidenceData) -> int:
        stamp = evidence.fetched_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
        conn.execute("""INSERT INTO evidence
            (competition_id, source_id, url, content_hash, raw_text, field_values_json, fetched_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(competition_id, url, content_hash) DO UPDATE
            SET last_seen_at = max(evidence.last_seen_at, excluded.last_seen_at)""",
            (competition_id, evidence.source_id, str(evidence.url), evidence.content_hash,
             evidence.raw_text, encode(evidence.field_values), stamp, stamp))
        row = conn.execute("SELECT id FROM evidence WHERE competition_id = ? AND url = ? AND content_hash = ?",
                           (competition_id, str(evidence.url), evidence.content_hash)).fetchone()
        return row["id"]

    def create_competition(self, data: CompetitionData, *, dedup_key: str | None = None,
                           evidence: EvidenceData | None = None, _connection: sqlite3.Connection | None = None) -> CompetitionRecord:
        stamp = utc_now()
        snapshot = encode(data.model_dump(mode="json"))
        with (nullcontext(_connection) if _connection is not None else self.database.transaction()) as conn:
            cursor = conn.execute("""INSERT INTO competitions
                (dedup_key, name, category, data_json, first_seen_at, last_checked_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""", (dedup_key, data.name, data.category, snapshot, stamp, stamp, stamp))
            competition_id = cursor.lastrowid
            evidence_id = self._insert_evidence(conn, competition_id, evidence) if evidence else None
            conn.execute("""INSERT INTO competition_history
                (competition_id, version, data_json, changes_json, reason, evidence_id, recorded_at)
                VALUES (?, 1, ?, '{}', 'first_seen', ?, ?)""", (competition_id, snapshot, evidence_id, stamp))
            return competition_record(conn.execute("SELECT * FROM competitions WHERE id = ?", (competition_id,)).fetchone())

    def get_competition(self, competition_id: int) -> CompetitionRecord:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM competitions WHERE id = ?", (competition_id,)).fetchone()
            if row is None:
                raise NotFoundError("Lomba tidak ditemukan.")
            return competition_record(row)

    def find_by_dedup_key(self, dedup_key: str) -> CompetitionRecord | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM competitions WHERE dedup_key = ?", (dedup_key,)).fetchone()
            return competition_record(row) if row else None

    def list_competitions(self, *, limit: int = 50, offset: int = 0) -> list[CompetitionRecord]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Batas pagination tidak valid.")
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM competitions ORDER BY first_seen_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset))
            return [competition_record(row) for row in rows]

    def update_competition(self, competition_id: int, data: CompetitionData, *, expected_version: int,
                           reason: str, evidence: EvidenceData | None = None, _connection: sqlite3.Connection | None = None) -> CompetitionRecord:
        if not reason.strip():
            raise ValueError("Alasan perubahan wajib diisi.")
        stamp = utc_now()
        new = data.model_dump(mode="json")
        snapshot = encode(new)
        with (nullcontext(_connection) if _connection is not None else self.database.transaction()) as conn:
            row = conn.execute("SELECT * FROM competitions WHERE id = ?", (competition_id,)).fetchone()
            if row is None:
                raise NotFoundError("Lomba tidak ditemukan.")
            if row["version"] != expected_version:
                raise VersionConflictError("Data lomba sudah berubah; baca versi terbaru sebelum menyimpan.")
            # Model defaults added by newer code are not source changes by themselves.
            previous = CompetitionData.model_validate_json(row["data_json"]).model_dump(mode="json")
            changes = {field: {"before": previous.get(field), "after": value}
                       for field, value in new.items() if previous.get(field) != value}
            evidence_id = self._insert_evidence(conn, competition_id, evidence) if evidence else None
            if changes:
                version = expected_version + 1
                conn.execute("""UPDATE competitions SET name = ?, category = ?, data_json = ?,
                    version = ?, last_checked_at = ?, updated_at = ? WHERE id = ?""",
                    (data.name, data.category, snapshot, version, stamp, stamp, competition_id))
                conn.execute("""INSERT INTO competition_history
                    (competition_id, version, data_json, changes_json, reason, evidence_id, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (competition_id, version, snapshot, encode(changes), reason, evidence_id, stamp))
            else:
                conn.execute("UPDATE competitions SET last_checked_at = ? WHERE id = ?", (stamp, competition_id))
            return competition_record(conn.execute("SELECT * FROM competitions WHERE id = ?", (competition_id,)).fetchone())

    def add_evidence(self, competition_id: int, evidence: EvidenceData) -> int:
        with self.database.transaction() as conn:
            return self._insert_evidence(conn, competition_id, evidence)

    def list_evidence(self, competition_id: int) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            result = []
            for row in conn.execute("SELECT * FROM evidence WHERE competition_id = ? ORDER BY id", (competition_id,)):
                item = dict(row)
                item["field_values"] = json.loads(item.pop("field_values_json"))
                result.append(item)
            return result

    def list_history(self, competition_id: int) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            result = []
            for row in conn.execute("SELECT * FROM competition_history WHERE competition_id = ? ORDER BY version", (competition_id,)):
                item = dict(row)
                item["data"] = json.loads(item.pop("data_json"))
                item["changes"] = json.loads(item.pop("changes_json"))
                result.append(item)
            return result

    def get_preferences(self) -> Preferences:
        with self.database.connection() as conn:
            row = conn.execute("SELECT data_json FROM preferences WHERE singleton = 1").fetchone()
            if row is None:
                raise NotFoundError("Preferensi belum diinisialisasi.")
            return Preferences.model_validate_json(row["data_json"])

    def save_preferences(self, preferences: Preferences) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE preferences SET data_json = ?, updated_at = ? WHERE singleton = 1",
                         (encode(preferences.model_dump(mode="json")), utc_now()))

    def create_job(self) -> int:
        # The database constraint rejects overlaps. Queue/recovery behavior is implemented in stage 5.
        with self.database.transaction() as conn:
            return conn.execute("INSERT INTO collection_jobs(requested_at) VALUES (?)", (utc_now(),)).lastrowid

    def start_manual_job(self) -> int:
        """Synchronous CLI run; queue dispatch and crash recovery are deferred to stage 5."""
        stamp = utc_now()
        with self.database.transaction() as conn:
            return conn.execute("""INSERT INTO collection_jobs
                (status, requested_at, started_at, heartbeat_at) VALUES ('running', ?, ?, ?)""",
                (stamp, stamp, stamp)).lastrowid

    def finish_manual_job(self, job_id: int, *, status: Literal["succeeded", "failed", "cancelled"], summary: dict[str, Any]) -> None:
        if status not in ("succeeded", "failed", "cancelled"):
            raise ValueError("Status akhir job tidak valid.")
        with self.database.transaction() as conn:
            cursor = conn.execute("""UPDATE collection_jobs SET status = ?, summary_json = ?, finished_at = ?
                WHERE id = ? AND status = 'running'""", (status, encode(summary), utc_now(), job_id))
            if cursor.rowcount != 1:
                raise NotFoundError("Job aktif tidak ditemukan.")

    def get_job(self, job_id: int) -> dict[str, Any]:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM collection_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise NotFoundError("Job tidak ditemukan.")
            item = dict(row)
            item["summary"] = json.loads(item.pop("summary_json"))
            return item

    def add_log(self, job_id: int, *, source_name: str, level: Literal["info", "warning", "error"],
                message: str, source_id: int | None = None, details: dict[str, Any] | None = None) -> int:
        with self.database.transaction() as conn:
            return conn.execute("""INSERT INTO collection_logs
                (job_id, source_id, source_name, level, message, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (job_id, source_id, source_name, level, message, encode(details or {}), utc_now())).lastrowid

    def list_logs(self, job_id: int) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            result = []
            for row in conn.execute("SELECT * FROM collection_logs WHERE job_id = ? ORDER BY id", (job_id,)):
                item = dict(row)
                item["details"] = json.loads(item.pop("details_json"))
                result.append(item)
            return result
