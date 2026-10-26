"""Durable manual jobs; adapters here use explicit fixtures and never the network."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI

from backend.app.config import ROOT
from backend.app.database import MIGRATIONS, Database
from backend.app.job_queue import CollectionBusyError, JobQueue, LostLeaseError, NoSourcesError
from backend.app.jobs import register_ou
from backend.app.jobs_api import router
from backend.app.models import SourceData
from backend.app.repository import Repository
from backend.app.worker import execute_job
from backend.app.collectors.ou_festival import extract
from backend.tests.test_collection import fixture_page


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "queue.db")
        self.database.migrate()
        self.repo = Repository(self.database)
        self.queue = JobQueue(self.database)
        self.source = register_ou(self.repo)
        self.adapter = Mock(return_value=extract(fixture_page()))

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, **kwargs):
        return execute_job(self.queue, *self.queue.claim(), adapters={self.source.adapter: self.adapter}, **kwargs)

    def expire(self, job_id):
        with self.database.transaction() as conn:
            conn.execute("UPDATE collection_jobs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?", (job_id,))

    def extra_source(self, **changes):
        return self.repo.create_source(SourceData(**{
            "name": "Fixture extra", "url": "https://example.com/fixture", "kind": "website", "adapter": "unsupported", **changes,
        }))

    def test_parallel_refresh_coalesces_and_workers_claim_once(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            requests = list(pool.map(lambda _: JobQueue(self.database).enqueue(), range(5)))
        self.assertEqual(sum(created for _, created in requests), 1)
        self.assertEqual(len({job_id for job_id, _ in requests}), 1)
        with ThreadPoolExecutor(max_workers=5) as pool:
            claims = list(pool.map(lambda _: JobQueue(self.database).claim(), range(5)))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        with self.assertRaises(CollectionBusyError):
            self.queue.enqueue(coalesce=False)
        self.adapter.assert_not_called()

    def test_one_failed_source_does_not_cancel_successful_source(self):
        broken = self.extra_source()
        job_id, _ = self.queue.enqueue()
        summary = self.run_job()
        self.assertEqual(self.queue.get(job_id)["status"], "partial")
        self.assertEqual((summary["sources_ok"], summary["sources_failed"]), (1, 1))
        self.assertEqual(len(self.repo.list_competitions()), 1)
        self.assertEqual(next(item for item in self.repo.list_sources() if item.id == broken.id).status, "failed")

    def test_partially_failed_batch_keeps_saved_results_and_reports_partial_job(self):
        from backend.app.collectors.public import Batch
        self.adapter.return_value = Batch([extract(fixture_page())], errors=['One article failed'], inspected=2)
        job_id, _ = self.queue.enqueue()
        summary = self.run_job()
        self.assertEqual(self.queue.get(job_id)['status'], 'partial')
        self.assertEqual(len(summary['results'][0]['competitions']), 1)
        self.assertEqual(len(self.repo.list_competitions()), 1)

    def test_unknown_instagram_is_reported_not_connected(self):
        source = self.extra_source(kind="instagram", url="https://www.instagram.com/fixture/")
        job_id, _ = self.queue.enqueue([source.id])
        self.run_job()
        self.assertEqual(self.queue.get(job_id)["status"], "failed")
        self.assertEqual(next(item for item in self.repo.list_sources() if item.id == source.id).status, "not_connected")
        self.adapter.assert_not_called()

    def test_disabled_or_deleted_after_enqueue_is_not_fetched(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                job_id, _ = self.queue.enqueue([self.source.id])
                if deleted:
                    self.repo.delete_source(self.source.id)
                else:
                    self.repo.set_source_enabled(self.source.id, False)
                summary = self.run_job()
                self.assertEqual(self.queue.get(job_id)["status"], "cancelled")
                self.assertEqual(summary["sources_skipped"], 1)
                self.adapter.assert_not_called()
                if not deleted:
                    self.repo.set_source_enabled(self.source.id, True)

    def test_source_disabled_during_fetch_cannot_store_event(self):
        def disable(*_):
            self.repo.set_source_enabled(self.source.id, False)
            return extract(fixture_page())
        self.adapter.side_effect = disable
        job_id, _ = self.queue.enqueue()
        self.run_job()
        self.assertEqual(self.queue.get(job_id)["status"], "cancelled")
        self.assertEqual(self.repo.list_competitions(), [])

    def test_heartbeat_keeps_live_owner_and_recovery_rejects_old_owner(self):
        job_id, _ = self.queue.enqueue()
        _, old_token = self.queue.claim()
        before = self.queue.get(job_id)["lease_expires_at"]
        self.queue.heartbeat(job_id, old_token)
        self.assertGreaterEqual(self.queue.get(job_id)["lease_expires_at"], before)
        self.queue.recover()
        self.assertIsNone(self.queue.claim())
        source = self.queue.pending_sources(job_id)[0]
        self.queue.start_source(job_id, old_token, source)
        self.expire(job_id)
        self.queue.recover()
        self.assertEqual(self.queue.get(job_id)["sources"][0]["status"], "pending")
        _, new_token = self.queue.claim()
        self.assertNotEqual(old_token, new_token)
        for action in (
            lambda: self.queue.heartbeat(job_id, old_token),
            lambda: self.queue.finish_source(job_id, old_token, source, error="stale"),
            lambda: self.queue.finish(job_id, old_token, cancelled=True),
        ):
            with self.assertRaises(LostLeaseError):
                action()
        self.assertEqual(self.queue.get(job_id)["attempts"], 2)

    def test_heartbeat_thread_runs_during_slow_adapter(self):
        pulse = threading.Event()
        original = self.queue.heartbeat
        def heartbeat(*args):
            original(*args)
            pulse.set()
        self.queue.lease_seconds = 3
        def slow(*_):
            self.assertTrue(pulse.wait(2.5), "No heartbeat during fetch")
            return extract(fixture_page())
        self.adapter.side_effect = slow
        self.queue.enqueue()
        with patch.object(self.queue, "heartbeat", side_effect=heartbeat):
            self.run_job()
        self.assertEqual(self.queue.latest()["status"], "succeeded")

    def test_stale_fetch_cannot_commit_competition_after_takeover(self):
        job_id, _ = self.queue.enqueue()
        def steal(*_):
            self.expire(job_id)
            self.queue.claim()  # Recovers and assigns a different owner.
            return extract(fixture_page())
        self.adapter.side_effect = steal
        with self.assertRaises(LostLeaseError):
            self.run_job()
        self.assertEqual(self.repo.list_competitions(), [])
        self.assertEqual(self.queue.get(job_id)["status"], "running")
        self.assertEqual(self.queue.get(job_id)["attempts"], 2)

    def test_crash_after_ingest_before_source_completion_is_idempotent(self):
        job_id, _ = self.queue.enqueue()
        with patch.object(self.queue, "finish_source", side_effect=SystemExit("Simulated process death")):
            with self.assertRaises(SystemExit):
                self.run_job()
        self.assertEqual(len(self.repo.list_competitions()), 1)
        self.expire(job_id)
        summary = self.run_job()
        self.assertEqual(summary["results"][0]["outcome"], "unchanged")
        self.assertEqual(len(self.repo.list_competitions()), 1)
        self.assertEqual(len(self.repo.list_history(1)), 1)
        self.assertEqual(len(self.repo.list_evidence(1)), 1)

    def test_recovery_skips_already_completed_source(self):
        self.extra_source()
        job_id, _ = self.queue.enqueue()
        def die(*args, **kwargs):
            if args[2]["source_id"] != self.source.id:
                raise SystemExit("Crash before next source")
            return original(*args, **kwargs)
        original = self.queue.start_source
        with patch.object(self.queue, "start_source", side_effect=die):
            with self.assertRaises(SystemExit):
                self.run_job()
        self.expire(job_id)
        self.run_job()
        self.adapter.assert_called_once()
        self.assertEqual(self.queue.get(job_id)["status"], "partial")

    def test_repeated_crashes_exhaust_three_attempts_and_release_queue(self):
        job_id, _ = self.queue.enqueue()
        for expected in range(1, 4):
            self.assertEqual(self.queue.claim()[0], job_id)
            self.assertEqual(self.queue.get(job_id)["attempts"], expected)
            self.expire(job_id)
            self.queue.recover()
        self.assertEqual(self.queue.get(job_id)["status"], "failed")
        self.assertEqual(self.queue.get(job_id)["sources"][0]["status"], "failed")
        self.assertIsNone(self.queue.claim())
        self.assertNotEqual(self.queue.enqueue()[0], job_id)

    def test_shutdown_and_keyboard_interrupt_cancel_and_count_skipped(self):
        self.queue.enqueue()
        self.adapter.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_job()
        job = self.queue.latest()
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["summary"]["sources_skipped"], 1)
        self.queue.enqueue()
        stop = threading.Event()
        stop.set()
        self.run_job(shutdown=stop)
        self.assertEqual(self.queue.latest()["status"], "cancelled")

    def test_malformed_or_inactive_source_selection_does_not_enqueue(self):
        for identifiers in ([], [999], [True], [0], ["1"]):
            with self.subTest(ids=identifiers), self.assertRaises(ValueError):
                self.queue.enqueue(identifiers)
        self.repo.set_source_enabled(self.source.id, False)
        with self.assertRaises(NoSourcesError):
            self.queue.enqueue()
        self.assertIsNone(self.queue.latest())

    def test_public_status_hides_worker_credential_and_source_configuration(self):
        job_id, _ = self.queue.enqueue()
        self.queue.claim()
        job = self.queue.get(job_id)
        self.assertNotIn("worker_token", job)
        self.assertNotIn("config_json", job["sources"][0])
        self.assertEqual(job["trigger"], "manual")

    def test_queued_request_survives_reopen_in_another_process(self):
        job_id, _ = self.queue.enqueue()
        code = """
import json, sys
from pathlib import Path
from backend.app.database import Database
from backend.app.job_queue import JobQueue
queue = JobQueue(Database(Path(sys.argv[1])))
job_id, token = queue.claim()
queue.finish(job_id, token, cancelled=True)
print(json.dumps(queue.get(job_id)))
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.database.path)], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["id"], job_id)
        self.assertEqual(self.queue.get(job_id)["status"], "cancelled")

    def test_worker_once_without_request_creates_no_jobs_or_sources(self):
        empty = Path(self.temp.name) / "empty.db"
        env = {**os.environ, "DATABASE_PATH": str(empty)}
        subprocess.run([sys.executable, "-m", "backend.app.worker", "--once"], cwd=ROOT,
                       env=env, capture_output=True, text=True, check=True)
        self.assertIsNone(JobQueue(Database(empty)).latest())
        self.assertEqual(Repository(Database(empty)).list_sources(), [])

    def test_schema_one_upgrade_preserves_event_and_recovers_legacy_running_job(self):
        directory = Path(self.temp.name) / "old_migrations"
        directory.mkdir()
        shutil.copy2(MIGRATIONS / "001_initial.sql", directory)
        path = Path(self.temp.name) / "old.db"
        old = Database(path, directory)
        old.migrate()
        repo = Repository(old)
        saved = repo.create_competition(extract(fixture_page()).data)
        job_id = repo.create_job()
        with old.transaction() as conn:
            conn.execute("UPDATE collection_jobs SET status='running',started_at='2000-01-01' WHERE id=?", (job_id,))
        upgraded = Database(path)
        self.assertEqual(upgraded.migrate(), ["002", "003"])
        queue = JobQueue(upgraded)
        queue.recover()
        self.assertEqual(queue.get(job_id)["status"], "failed")
        self.assertEqual(Repository(upgraded).get_competition(saved.id), saved)


class ApiTests(unittest.TestCase):
    setUp = QueueTests.setUp
    tearDown = QueueTests.tearDown
    run_job = QueueTests.run_job

    def request(self, method, path, body=None, headers=None):
        app = FastAPI()
        app.state.database = self.database
        for item in getattr(self, "routers", (router,)):
            app.include_router(item)
        if getattr(self, "protect", False):
            from backend.app.security import protect_writes
            app.middleware("http")(protect_writes)
        payload = json.dumps(body).encode() if body is not None else b""
        messages = []
        async def receive():
            return {"type": "http.request", "body": payload, "more_body": False}
        async def send(message):
            messages.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": path.split("?")[0], "raw_path": path.split("?")[0].encode(), "query_string": path.partition("?")[2].encode(),
                 "root_path": "", "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 9000),
                 "headers": [(key.encode(), value.encode()) for key, value in {
                     "content-type": "application/json", **(headers or {}),
                 }.items()]}
        asyncio.run(app(scope, receive, send))
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, json.loads(content)

    def test_api_enqueue_is_immediate_persistent_and_coalesced_without_fetch(self):
        headers = {"x-lomba-radar": "1", "origin": "http://localhost:5173"}
        status, body = self.request("POST", "/api/refresh", {}, headers)
        self.assertEqual(status, 202)
        self.assertTrue(body["created"])
        self.assertEqual(body["job"]["status"], "queued")
        _, repeated = self.request("POST", "/api/refresh", {}, headers)
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["id"], body["id"])
        self.assertEqual(self.request("GET", "/api/jobs/latest")[1]["job"]["id"], body["id"])
        self.run_job()
        status, completed = self.request("GET", f"/api/jobs/{body['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "succeeded")
        self.adapter.assert_called_once()

    def test_api_rejects_missing_header_foreign_origin_and_bad_input(self):
        for headers in ({}, {"x-lomba-radar": "1", "origin": "https://attacker.example"}):
            self.assertEqual(self.request("POST", "/api/refresh", {}, headers)[0], 403)
        for body in ({"source_ids": []}, {"source_ids": [True]}, {"source_ids": [0]}, {"source_ids": ["1"]}, {"unknown": 1}):
            self.assertEqual(self.request("POST", "/api/refresh", body, {"x-lomba-radar": "1"})[0], 422)
        self.assertIsNone(self.queue.latest())

    def test_api_reports_missing_job_and_no_sources(self):
        self.assertEqual(self.request("GET", "/api/jobs/latest")[1], {"job": None})
        self.assertEqual(self.request("GET", "/api/jobs/999")[0], 404)
        self.assertEqual(self.request("GET", "/api/jobs/0")[0], 422)
        self.repo.set_source_enabled(self.source.id, False)
        self.assertEqual(self.request("POST", "/api/refresh", {}, {"x-lomba-radar": "1"})[0], 409)
