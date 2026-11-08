import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.automation import AutomationSettings, AutomationStore
from backend.app.automation_api import present
from backend.app.collectors.public import collect_html
from backend.app.collectors.http import Page, FetchError
from backend.app.config import ROOT
from backend.app.database import Database, MIGRATIONS
from backend.app.job_queue import JobQueue
from backend.app.models import SourceData
from backend.app.repository import Repository
from backend.app.scheduler import Scheduler
from backend.app.scheduled_collection import ScheduledPageClient
from backend.app.worker import execute_job
from backend.tests import test_jobs as jobs
from backend.tests.test_collection import fixture_page


class SchedulerTests(unittest.TestCase):
    setUp = jobs.QueueTests.setUp
    tearDown = jobs.QueueTests.tearDown
    now = datetime(2030,1,1,tzinfo=timezone.utc)

    def enable(self, **changes):
        store = AutomationStore(self.database)
        previous = store.get()
        settings = {**previous['settings'].model_dump(mode='json'),**changes}
        return store.save(AutomationSettings.model_validate({**settings,'enabled':True}), expected_version=previous['version'])

    def pause(self):
        store = AutomationStore(self.database)
        snapshot = store.get()
        return store.save(snapshot['settings'].model_copy(update={'enabled':False}),expected_version=snapshot['version'])

    def tick(self, now=None):
        return Scheduler(self.database).tick(now=now or self.now)

    def complete(self, job_id):
        claimed = self.queue.claim(job_id=job_id)
        self.queue.finish(*claimed,cancelled=True)

    def test_disabled_start_creates_no_job_sources_or_network(self):
        with patch('backend.app.collectors.http.PublicClient.get',side_effect=AssertionError('network')):
            self.assertEqual(self.tick()['state'],'disabled')
        self.assertIsNone(self.queue.latest())
        self.assertEqual(len(self.repo.list_sources()),1)

    def test_first_due_job_and_next_interval_survive_reopen(self):
        self.enable(interval_minutes=60)
        first = self.tick()
        self.assertEqual(first['state'],'enqueued')
        self.assertEqual(self.queue.get(first['job_id'])['trigger'],'scheduled')
        self.assertEqual(self.repo.get_job(first['job_id'])['trigger'],'scheduled')
        self.complete(first['job_id'])
        self.assertEqual(Scheduler(Database(self.database.path)).tick(now=self.now+timedelta(minutes=59))['state'],'waiting')
        self.assertEqual(self.tick(self.now+timedelta(minutes=60))['state'],'enqueued')

    def test_multiple_scheduler_processes_only_enqueue_once(self):
        self.enable()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _:Scheduler(Database(self.database.path)).tick(now=self.now),range(5)))
        self.assertEqual(sum(row['state']=='enqueued' for row in results),1)
        with self.database.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM collection_jobs').fetchone()[0],1)

    def test_manual_active_job_delays_schedule_without_changing_its_origin(self):
        manual,_ = self.queue.enqueue()
        self.enable()
        self.assertEqual(self.tick()['state'],'busy')
        self.assertEqual(self.queue.get(manual)['trigger'],'manual')
        self.complete(manual)
        self.assertEqual(self.tick()['state'],'enqueued')

    def test_manual_refresh_coalesces_with_automatic_job(self):
        self.enable()
        scheduled = self.tick()['job_id']
        job_id,created = self.queue.enqueue()
        self.assertEqual(job_id,scheduled)
        self.assertFalse(created)
        self.assertEqual(self.queue.get(job_id)['trigger'],'scheduled')

    def test_long_downtime_dispatches_one_job_without_catchup_storm(self):
        self.enable(interval_minutes=30)
        first = self.tick()['job_id']
        self.complete(first)
        later = self.now+timedelta(days=30)
        result = self.tick(later)
        self.assertEqual(result['state'],'enqueued')
        self.complete(result['job_id'])
        self.assertEqual(self.tick(later)['state'],'waiting')
        self.assertEqual(AutomationStore(self.database).schedule()['next_run_at'],(later+timedelta(minutes=30)).isoformat(timespec='microseconds'))

    def test_source_cap_rotation_includes_instagram_but_excludes_discovery_without_preference(self):
        extra = self.repo.create_source(SourceData(name='Free',kind='website',url='https://example.com/',adapter='public_html'))
        instagram = self.repo.create_source(SourceData(name='IG',kind='instagram',url='https://www.instagram.com/fixture/',adapter='instagram_provider'))
        self.repo.create_source(SourceData(name='Brave',kind='website',url='https://api.search.brave.com/',adapter='brave_discovery'))
        self.enable(interval_minutes=30,max_sources_per_run=1,max_new_sources_per_run=0,
                    allow_paid_providers=True,provider_daily_request_limit=10,provider_daily_budget_usd='1.00')
        first = self.tick()['job_id']
        self.assertEqual([row['source_id'] for row in self.queue.pending_sources(first)],[self.source.id])
        self.complete(first)
        second = self.tick(self.now+timedelta(minutes=30))['job_id']
        self.assertEqual([row['source_id'] for row in self.queue.pending_sources(second)],[extra.id])
        self.complete(second)
        third = self.tick(self.now+timedelta(minutes=60))['job_id']
        self.assertEqual([row['source_id'] for row in self.queue.pending_sources(third)],[instagram.id])

    def test_no_eligible_sources_preserves_clear_status_and_waits_for_interval(self):
        self.repo.set_source_enabled(self.source.id,False)
        self.enable()
        self.assertEqual(self.tick()['state'],'no_sources')
        self.assertIsNone(self.queue.latest())
        self.assertEqual(self.tick(self.now+timedelta(seconds=5))['state'],'no_sources')

    def test_pause_prevents_dispatch_and_queued_scheduled_fetch(self):
        self.enable()
        job_id = self.tick()['job_id']
        self.pause()
        self.assertEqual(self.tick()['state'],'disabled')
        execute_job(self.queue,*self.queue.claim(),adapters={self.source.adapter:self.adapter})
        self.adapter.assert_not_called()
        self.assertEqual(self.queue.get(job_id)['status'],'cancelled')
        self.assertIsNone(AutomationStore(self.database).schedule()['next_run_at'])

    def test_pause_during_fetch_blocks_ingest_and_other_sources(self):
        self.repo.create_source(SourceData(name='Next',kind='website',url='https://example.com/',adapter='public_html'))
        self.enable()
        job_id = self.tick()['job_id']
        original = self.adapter.return_value
        def pause(*_):
            self.pause()
            return original
        self.adapter.side_effect = pause
        later = Mock(side_effect=AssertionError('Fetch after pause'))
        execute_job(self.queue,*self.queue.claim(),adapters={self.source.adapter:self.adapter,'public_html':later})
        self.assertEqual(self.repo.list_competitions(),[])
        later.assert_not_called()
        self.assertEqual(self.queue.get(job_id)['status'],'cancelled')

    def test_saved_job_limits_are_immutable_after_settings_change(self):
        self.enable(max_pages_per_source=1)
        job_id = self.tick()['job_id']
        self.enable(max_pages_per_source=10)
        self.assertEqual(self.queue.automation_settings(job_id).max_pages_per_source,1)

    def test_scheduled_worker_persists_real_fixture_without_frontend(self):
        self.enable(max_pages_per_source=1)
        job_id = self.tick()['job_id']
        client = Mock(); client.get.return_value = fixture_page()
        reopened = JobQueue(Database(self.database.path))
        execute_job(reopened,*reopened.claim(),client=client)
        self.assertEqual(reopened.get(job_id)['status'],'succeeded')
        self.assertEqual(len(self.repo.list_competitions()),1)
        client.get.assert_called_once()

    def test_page_cap_blocks_further_gets_before_network(self):
        delegate = Mock(); delegate.get.return_value = Page('https://example.com/',b'<html></html>','text/html')
        client = ScheduledPageClient('https://example.com/',1,delegate)
        client.get('https://example.com/')
        with self.assertRaises(FetchError): client.get('https://example.com/other')
        delegate.get.assert_called_once()

    def test_list_page_counts_towards_per_source_budget(self):
        delegate = Mock()
        delegate.get.return_value = Page('https://example.com/',b'<a class="item" href="/one">Business plan</a><a class="item" href="/two">BCC</a>','text/html')
        client = ScheduledPageClient('https://example.com/',1,delegate)
        batch = collect_html({'source_url':'https://example.com/','config_json':'{"links_selector":".item"}'},client)
        delegate.get.assert_called_once()
        self.assertEqual(batch.items,[])
        self.assertTrue(batch.errors)

    def test_crash_does_not_reset_durable_source_page_budget(self):
        self.enable(max_pages_per_source=1)
        job_id = self.tick()['job_id']
        delegate = Mock(); delegate.get.return_value = fixture_page()
        def interrupted(source,client):
            client.get(source['source_url'])
            raise SystemExit('Crash after fetch')
        with self.assertRaises(SystemExit):
            execute_job(self.queue,*self.queue.claim(),client=delegate,adapters={self.source.adapter:interrupted})
        with self.database.transaction() as conn:
            conn.execute("UPDATE collection_jobs SET lease_expires_at='2000-01-01' WHERE id=?",(job_id,))
        execute_job(self.queue,*self.queue.claim(),client=delegate)
        delegate.get.assert_called_once()
        self.assertEqual(self.queue.get(job_id)['status'],'failed')
        self.assertTrue(any('Batas halaman' in row['message'] for row in self.queue.get(job_id)['logs']))

    def test_settings_interval_change_reschedules_but_other_edits_keep_next_due(self):
        self.enable()
        self.tick()
        previous = AutomationStore(self.database).schedule()['next_run_at']
        self.enable(max_pages_per_source=2)
        self.assertEqual(AutomationStore(self.database).schedule()['next_run_at'],previous)
        self.enable(interval_minutes=30)
        next_at = datetime.fromisoformat(AutomationStore(self.database).schedule()['next_run_at'])
        self.assertAlmostEqual((next_at-datetime.now(timezone.utc)).total_seconds(),1800,delta=5)

    def test_expired_worker_recovers_existing_job_without_new_dispatch(self):
        self.enable(interval_minutes=30)
        job_id = self.tick()['job_id']
        self.queue.claim()
        with self.database.transaction() as conn:
            conn.execute("UPDATE collection_jobs SET lease_expires_at='2000-01-01' WHERE id=?",(job_id,))
        self.assertEqual(self.tick(self.now+timedelta(hours=1))['state'],'busy')
        self.assertEqual(self.queue.get(job_id)['status'],'queued')
        self.assertEqual(self.queue.latest()['id'],job_id)

    def test_dispatch_failure_rolls_back_job_and_schedule_together(self):
        self.enable()
        before = AutomationStore(self.database).schedule()
        scheduler = Scheduler(self.database)
        original = scheduler.queue._enqueue_sources
        def broken(*args,**kwargs):
            original(*args,**kwargs)
            raise sqlite3.OperationalError('Simulated disk error')
        with patch.object(scheduler.queue,'_enqueue_sources',side_effect=broken):
            with self.assertRaises(sqlite3.OperationalError): scheduler.tick(now=self.now)
        self.assertIsNone(self.queue.latest())
        self.assertEqual(AutomationStore(self.database).schedule(),before)

    def test_scheduler_cli_restart_does_not_duplicate_jobs_or_fetch(self):
        self.enable()
        env = {**os.environ,'DATABASE_PATH':str(self.database.path),'PYTHONIOENCODING':'utf-8'}
        for _ in range(2):
            subprocess.run([sys.executable,'-m','backend.app.scheduler','--once'],cwd=ROOT,env=env,
                           capture_output=True,text=True,check=True,timeout=20)
        self.assertEqual(self.queue.latest()['id'],1)
        self.assertEqual(self.queue.latest()['status'],'queued')
        self.assertEqual(self.repo.list_competitions(),[])

    def test_runtime_indicates_stale_scheduler_instead_of_claiming_running(self):
        self.enable()
        scheduler = Scheduler(self.database)
        scheduler.tick()
        store = AutomationStore(self.database)
        self.assertTrue(present(store.get(),store.schedule())['runtime']['scheduler_online'])
        with self.database.transaction() as conn:
            conn.execute("UPDATE automation_schedule SET last_tick_at='2000-01-01T00:00:00+00:00'")
        result = present(store.get(),store.schedule())['runtime']
        self.assertFalse(result['running'])
        self.assertEqual(result['state'],'waiting_scheduler')

    def test_migration_preserves_old_jobs_logs_evidence_and_enabled_intent(self):
        old_dir = Path(self.temp.name)/'old'
        old_dir.mkdir()
        for file in MIGRATIONS.glob('*.sql'):
            if file.name < '005': shutil.copy2(file,old_dir)
        path = Path(self.temp.name)/'upgrade.db'
        old = Database(path,old_dir); old.migrate()
        repo = Repository(old)
        saved = repo.create_competition(self.adapter.return_value.data)
        job_id = repo.create_job()
        repo.add_log(job_id,source_name='Fixture',level='info',message='Kept')
        with old.transaction() as conn:
            conn.execute("UPDATE automation_settings SET data_json=json_set(data_json,'$.enabled',json('true'))")
        upgraded = Database(path)
        self.assertEqual(upgraded.migrate(),['005','006','007','008','009','010','011'])
        self.assertEqual(Repository(upgraded).get_competition(saved.id),saved)
        self.assertEqual(JobQueue(upgraded).get(job_id)['logs'][0]['message'],'Kept')
        self.assertTrue(AutomationStore(upgraded).get()['settings'].enabled)
        self.assertEqual(Scheduler(upgraded).tick()['state'],'busy')
