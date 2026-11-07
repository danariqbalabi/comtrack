"""All example competitions are test fixtures in temporary databases, never app seed data."""

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Response
from pydantic import ValidationError

from backend.app.config import ROOT, Settings
from backend.app.database import MIGRATIONS, Database, MigrationError
from backend.app.main import health, lifespan
from backend.app.models import CompetitionData, EvidenceData, Money, Preferences, SourceData, TimelineEntry
from backend.app.repository import NotFoundError, Repository, VersionConflictError


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "radar.db"
        self.db = Database(self.path)
        self.db.migrate()
        self.repo = Repository(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, **changes):
        return CompetitionData.model_validate({
            "name": "Fixture BPC 2030", "category": "BPC", "source_url": "https://example.com/bpc",
            "timeline": [{"kind": "registration", "raw_text": "31 Desember 2030", "date": "2030-12-31", "needs_review": False}],
            **changes,
        })

    def evidence(self, text="Pendaftaran: 31 Desember 2030", source_id=None, url="https://example.com/bpc"):
        return EvidenceData(
            source_id=source_id, url=url, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            raw_text=text, field_values={"timeline.0.date": text}, fetched_at=datetime.now(timezone.utc),
        )

    def source(self):
        return self.repo.create_source(SourceData(name="Fixture source", kind="website", url="https://example.com/bpc", adapter="page"))

    def test_repeat_migration_preserves_preferences_and_has_no_demo_data(self):
        preferences = Preferences(categories=["BPC"], hide_closed=False)
        self.repo.save_preferences(preferences)
        self.assertEqual(self.db.migrate(), [])
        self.assertEqual(self.repo.get_preferences(), preferences)
        self.assertEqual(self.repo.list_competitions(), [])
        self.assertEqual(self.repo.list_sources(), [])
        self.assertEqual(self.db.check(), "006")

    def test_persistence_across_a_separate_python_process(self):
        source = self.source()
        saved = self.repo.create_competition(self.fixture(), dedup_key="fixture-2030", evidence=self.evidence(source_id=source.id))
        self.repo.save_preferences(Preferences(categories=["BCC"]))
        code = """
import json, sys
from pathlib import Path
from backend.app.database import Database
from backend.app.repository import Repository
database = Database(Path(sys.argv[1]))
assert database.migrate() == []
repo = Repository(database)
print(json.dumps({'name': repo.get_competition(1).data.name, 'sources': len(repo.list_sources()),
                  'evidence': len(repo.list_evidence(1)), 'categories': repo.get_preferences().categories}))
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"name": saved.data.name, "sources": 1, "evidence": 1, "categories": ["BCC"]})

    def test_update_is_atomic_and_retains_evidence_and_history(self):
        saved = self.repo.create_competition(self.fixture(), evidence=self.evidence())
        changed = self.fixture(timeline=[{"kind": "registration", "raw_text": "5 Januari 2031", "date": "2031-01-05", "needs_review": False}])
        updated = self.repo.update_competition(saved.id, changed, expected_version=1, reason="source_changed",
                                             evidence=self.evidence("Diperpanjang: 5 Januari 2031"))
        history = self.repo.list_history(saved.id)
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.first_seen_at, saved.first_seen_at)
        self.assertEqual(len(self.repo.list_evidence(saved.id)), 2)
        self.assertEqual(history[0]["data"]["timeline"][0]["date"], "2030-12-31")
        self.assertEqual(history[1]["changes"]["timeline"]["after"][0]["date"], "2031-01-05")
        self.assertIsNotNone(history[1]["evidence_id"])

    def test_unchanged_observation_does_not_add_revision_or_evidence(self):
        evidence = self.evidence()
        saved = self.repo.create_competition(self.fixture(), evidence=evidence)
        later = evidence.model_copy(update={"fetched_at": datetime(2031, 1, 1, tzinfo=timezone.utc)})
        updated = self.repo.update_competition(saved.id, saved.data, expected_version=1, reason="checked_again", evidence=later)
        self.assertEqual(updated.version, 1)
        self.assertEqual(updated.updated_at, saved.updated_at)
        self.assertEqual(len(self.repo.list_history(saved.id)), 1)
        rows = self.repo.list_evidence(saved.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_text"], evidence.raw_text)
        self.assertTrue(rows[0]["last_seen_at"].startswith("2031-01-01"))

    def test_two_sources_can_attach_evidence_to_one_competition(self):
        saved = self.repo.create_competition(self.fixture(), evidence=self.evidence())
        self.repo.add_evidence(saved.id, self.evidence(url="https://example.org/announcement"))
        self.assertEqual(len(self.repo.list_evidence(saved.id)), 2)
        self.assertEqual(len(self.repo.list_competitions()), 1)

    def test_invalid_foreign_key_rolls_back_event_and_initial_history(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_competition(self.fixture(), evidence=self.evidence(source_id=999))
        with self.db.connection() as conn:
            for table in ("competitions", "evidence", "competition_history"):
                self.assertEqual(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_invalid_update_evidence_rolls_back_all_changes(self):
        saved = self.repo.create_competition(self.fixture())
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.update_competition(saved.id, self.fixture(summary="changed"), expected_version=1,
                                         reason="update", evidence=self.evidence(source_id=999))
        self.assertEqual(self.repo.get_competition(saved.id), saved)
        self.assertEqual(len(self.repo.list_history(saved.id)), 1)

    def test_stale_writer_cannot_overwrite_newer_data(self):
        saved = self.repo.create_competition(self.fixture())
        self.repo.update_competition(saved.id, self.fixture(summary="new"), expected_version=1, reason="first_writer")
        with self.assertRaises(VersionConflictError):
            self.repo.update_competition(saved.id, self.fixture(summary="stale"), expected_version=1, reason="stale_writer")
        self.assertEqual(self.repo.get_competition(saved.id).data.summary, "new")

    def test_explicit_dedup_key_is_unique_but_different_editions_can_coexist(self):
        first = self.repo.create_competition(self.fixture(), dedup_key="bpc-2030")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_competition(self.fixture(), dedup_key="bpc-2030")
        self.repo.create_competition(self.fixture(name="Fixture BPC 2031"), dedup_key="bpc-2031")
        self.assertEqual(self.repo.find_by_dedup_key("bpc-2030").id, first.id)
        self.assertEqual(len(self.repo.list_competitions()), 2)

    def test_delete_source_keeps_evidence_and_logs(self):
        source = self.source()
        saved = self.repo.create_competition(self.fixture(), evidence=self.evidence(source_id=source.id))
        job = self.repo.create_job()
        self.repo.add_log(job, source_id=source.id, source_name=source.name, level="error", message="HTTP 403")
        self.repo.delete_source(source.id)
        self.db.migrate()
        self.assertEqual(self.repo.list_sources(), [])
        evidence = self.repo.list_evidence(saved.id)[0]
        self.assertIsNone(evidence["source_id"])
        self.assertEqual(evidence["url"], "https://example.com/bpc")
        self.assertEqual(self.repo.list_logs(job)[0]["source_name"], source.name)

    def test_disabled_source_and_job_survive_reopen(self):
        source = self.source()
        self.repo.set_source_enabled(source.id, False)
        job = self.repo.create_job()
        reopened = Repository(Database(self.path))
        self.assertEqual(reopened.list_sources(enabled_only=True), [])
        self.assertFalse(reopened.list_sources()[0].enabled)
        self.assertEqual(reopened.get_job(job)["status"], "queued")
        self.assertEqual(reopened.get_job(job)["trigger"], "manual")

    def test_active_job_constraint_prevents_overlap(self):
        job = self.repo.create_job()
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_job()
        with self.db.transaction() as conn:
            conn.execute("UPDATE collection_jobs SET status = 'succeeded' WHERE id = ?", (job,))
        self.assertNotEqual(self.repo.create_job(), job)

    def test_missing_records_and_bad_pagination_fail_explicitly(self):
        with self.assertRaises(NotFoundError): self.repo.get_competition(999)
        with self.assertRaises(NotFoundError): self.repo.delete_source(999)
        with self.assertRaises(ValueError): self.repo.list_competitions(limit=1000)

    def test_migration_failure_rolls_back_new_schema(self):
        migrations = Path(self.temp.name) / "migrations"
        shutil.copytree(MIGRATIONS, migrations)
        (migrations / "007_broken.sql").write_text("CREATE TABLE should_rollback (id INTEGER);\nINVALID SQL;\n", encoding="utf8")
        with self.assertRaises(sqlite3.OperationalError): Database(self.path, migrations).migrate()
        with self.db.connection() as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name = 'should_rollback'").fetchone())
        self.assertEqual(self.db.check(), "006")

    def test_changed_applied_migration_is_rejected(self):
        migrations = Path(self.temp.name) / "migrations"
        shutil.copytree(MIGRATIONS, migrations)
        file = migrations / "001_initial.sql"
        file.write_text(file.read_text(encoding="utf8") + "\n-- changed\n", encoding="utf8")
        with self.assertRaises(MigrationError): Database(self.path, migrations).migrate()

    def test_appended_migration_preserves_existing_records(self):
        saved = self.repo.create_competition(self.fixture())
        migrations = Path(self.temp.name) / "migrations"
        shutil.copytree(MIGRATIONS, migrations)
        (migrations / "007_add_note.sql").write_text("ALTER TABLE competitions ADD COLUMN internal_note TEXT;\n", encoding="utf8")
        upgraded = Database(self.path, migrations)
        self.assertEqual(upgraded.migrate(), ["007"])
        self.assertEqual(upgraded.migrate(), [])
        self.assertEqual(upgraded.check(), "007")
        self.assertEqual(Repository(upgraded).get_competition(saved.id), saved)
        with self.assertRaises(MigrationError):
            self.db.migrate()  # Older code must not silently accept a newer database.

    def test_parallel_migration_initializes_exactly_once(self):
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                path = Path(self.temp.name) / f"parallel-{attempt}.db"
                with ThreadPoolExecutor(max_workers=3) as pool:
                    results = list(pool.map(lambda _: Database(path).migrate(), range(3)))
                self.assertEqual(sum(result == ["001", "002", "003", "004", "005", "006"] for result in results), 1)

    def test_lifespan_initializes_database_and_health_checks_it(self):
        settings = Settings(database_path=Path(self.temp.name) / "startup.db")
        application = FastAPI()
        async def start():
            with patch("backend.app.main.get_settings", return_value=settings):
                async with lifespan(application):
                    response = health(Response(), settings, application.state.database)
                    self.assertEqual(response.database, "ok")
                    self.assertEqual(response.schema_version, "006")
        asyncio.run(start())

    def test_health_does_not_claim_uninitialized_database_is_ready(self):
        with self.assertRaises(HTTPException) as ctx:
            with self.assertLogs("backend.app.main", level="ERROR"):
                health(Response(), Settings(), Database(Path(self.temp.name) / "empty.db"))
        self.assertEqual(ctx.exception.status_code, 503)


class ContractTests(unittest.TestCase):
    def test_unknown_dates_and_currency_are_not_filled_in(self):
        timeline = TimelineEntry(kind="registration", raw_text="12 November")
        self.assertIsNone(timeline.date)
        self.assertIsNone(timeline.at)
        self.assertIsNone(timeline.timezone)
        self.assertTrue(timeline.needs_review)
        money = Money(raw_text="Biaya menyusul")
        self.assertIsNone(money.amount)
        self.assertIsNone(money.currency)

    def test_money_does_not_lose_decimal_precision(self):
        money = Money(amount="123456789.01", currency="IDR", basis="team", raw_text="fixture")
        self.assertEqual(Money.model_validate_json(money.model_dump_json()).amount, money.amount)

    def test_invalid_contracts_are_rejected(self):
        with self.assertRaises(ValidationError): Money(amount=-1, raw_text="fixture")
        with self.assertRaises(ValidationError): Preferences(categories=[])
        with self.assertRaises(ValidationError): Preferences(country="US")
        with self.assertRaises(ValidationError):
            TimelineEntry(kind="registration", raw_text="fixture", at="2030-01-01T23:59:00")
        with self.assertRaises(ValidationError):
            CompetitionData(name="fixture", source_url="file:///secret", team_min=4, team_max=2)
        with self.assertRaises(ValidationError):
            CompetitionData(name="fixture", source_url="https://example.com", team_min=4, team_max=2)

    def test_relative_database_path_is_independent_of_current_directory(self):
        settings = Settings(database_path="data/custom.db")
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                self.assertEqual(settings.resolved_database_path, ROOT / "data" / "custom.db")
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
