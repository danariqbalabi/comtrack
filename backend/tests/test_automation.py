import base64
import json
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.app.automation import AutomationSettings, AutomationStore
from backend.app.automation_api import router
from backend.app.config import Settings
from backend.app.database import Database, MIGRATIONS
from backend.app.models import Preferences
from backend.app.repository import Repository, VersionConflictError
from backend.tests import test_jobs as jobs


class AutomationTests(unittest.TestCase):
    setUp = jobs.QueueTests.setUp
    tearDown = jobs.QueueTests.tearDown
    request = jobs.ApiTests.request
    routers = (router,)
    protect = True
    headers = {'x-lomba-radar':'1'}

    def read(self):
        status, body = self.request('GET', '/api/automation')
        self.assertEqual(status, 200)
        return body

    def update(self, snapshot, **changes):
        return self.request('PUT', '/api/automation', {
            'settings':{**snapshot['settings'], **changes}, 'expected_version':snapshot['version']}, self.headers)

    def test_fresh_database_defaults_disabled_with_zero_paid_allowance(self):
        body = self.read()
        self.assertFalse(body['settings']['enabled'])
        self.assertFalse(body['settings']['allow_paid_providers'])
        self.assertEqual(body['settings']['provider_daily_request_limit'], 0)
        self.assertEqual(float(body['settings']['provider_daily_budget_usd']), 0)
        self.assertTrue(body['runtime']['scheduler_available'])
        self.assertFalse(body['runtime']['running'])
        self.assertTrue(body['runtime']['limits_enforced'])
        self.assertEqual(body['runtime']['state'], 'disabled')
        self.assertEqual(body['version'], 1)

    def test_save_persists_across_reopen_without_dispatch_or_network(self):
        with patch('backend.app.collectors.http.PublicClient.get', side_effect=AssertionError('Unexpected fetch')), \
             patch('backend.app.collectors.providers.request_json', side_effect=AssertionError('Unexpected provider call')):
            status, saved = self.update(self.read(), enabled=True, interval_minutes=60,
                max_sources_per_run=20, max_pages_per_source=2, max_images_per_post=0)
            self.assertEqual(status, 200)
            self.assertEqual(saved['runtime']['state'], 'waiting_scheduler')
            self.assertFalse(saved['runtime']['running'])
            reopened = AutomationStore(Database(self.database.path)).get()
            self.assertEqual(reopened['settings'].interval_minutes, 60)
            self.assertEqual(reopened['version'], 2)
            self.assertIsNone(self.queue.latest())
            self.assertEqual(self.repo.list_competitions(), [])
        self.assertEqual(self.update(self.read(), enabled=False)[0], 200)
        self.assertEqual(self.read()['runtime']['state'], 'disabled')

    def test_invalid_limits_never_overwrite_saved_configuration(self):
        original = self.read()
        cases = [
            {'interval_minutes':29}, {'interval_minutes':10081}, {'interval_minutes':True},
            {'interval_minutes':'60'}, {'interval_minutes':60.5}, {'enabled':'true'},
            {'max_sources_per_run':31}, {'max_sources_per_run':0},
            {'max_new_sources_per_run':11}, {'max_new_sources_per_run':-1},
            {'max_pages_per_source':11}, {'max_images_per_post':6},
            {'provider_daily_budget_usd':'-0.01'}, {'provider_daily_budget_usd':'0.001'},
            {'provider_daily_budget_usd':'NaN'}, {'provider_daily_budget_usd':'Infinity'},
            {'provider_daily_request_limit':-1}, {'provider_daily_request_limit':10001},
            {'allow_paid_providers':True}, {'instagram_public_competition_accounts_only':False},
            {'instagram_public_competition_accounts_only':1},
            {'api_key':'never-store-me'},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.update(original, **changes)[0], 422)
        self.assertEqual(self.read()['settings'], original['settings'])
        self.assertEqual(self.read()['version'], original['version'])

    def test_paid_intent_needs_positive_caps_but_does_not_enable_unconfigured_provider(self):
        with patch('backend.app.automation_api.get_settings', return_value=Settings(_env_file=None)):
            status, result = self.update(self.read(), allow_paid_providers=True,
                provider_daily_request_limit=12, provider_daily_budget_usd='0.25')
            self.assertEqual(status, 200)
            self.assertEqual(result['settings']['provider_daily_budget_usd'], '0.25')
            for key in ('discovery','instagram'):
                self.assertFalse(result['runtime']['providers'][key]['configured'])
                self.assertFalse(result['runtime']['providers'][key]['automation_allowed'])

    def test_readiness_reports_only_configuration_without_disclosing_secrets(self):
        settings = Settings(_env_file=None, instagram_provider_enabled=True, apify_token='fixture-private-token',
                            discovery_provider_enabled=True, brave_api_key='fixture-private-search')
        with patch('backend.app.automation_api.get_settings', return_value=settings), \
             patch('backend.app.collectors.providers.request_json', side_effect=AssertionError('Readiness called provider')):
            body = self.read()
        self.assertTrue(body['runtime']['providers']['instagram']['configured'])
        self.assertFalse(body['runtime']['providers']['instagram']['automation_allowed'])
        self.assertNotIn('fixture-private', json.dumps(body))

    def test_stale_browser_save_is_rejected_instead_of_overwriting(self):
        original = self.read()
        self.assertEqual(self.update(original, interval_minutes=120)[0], 200)
        self.assertEqual(self.update(original, interval_minutes=240)[0], 409)
        self.assertEqual(self.read()['settings']['interval_minutes'], 120)

    def test_parallel_saves_allow_only_one_writer(self):
        def write(interval):
            try:
                AutomationStore(Database(self.database.path)).save(AutomationSettings(interval_minutes=interval), expected_version=1)
                return True
            except VersionConflictError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(write, (60,120))), 1)
        self.assertEqual(self.read()['version'], 2)

    def test_api_write_protection_and_private_access_apply(self):
        body = {'settings':self.read()['settings'], 'expected_version':1}
        self.assertEqual(self.request('PUT','/api/automation',body)[0],403)
        self.assertEqual(self.request('PUT','/api/automation',body,{**self.headers,'origin':'https://untrusted.example'})[0],403)
        private = Settings(_env_file=None, access_username='radar', access_password='fixture-password')
        with patch('backend.app.security.get_settings',return_value=private):
            self.assertEqual(self.request('GET','/api/automation')[0],401)
            auth = 'Basic ' + base64.b64encode(b'radar:fixture-password').decode()
            self.assertEqual(self.request('GET','/api/automation',headers={'authorization':auth})[0],200)

    def test_configuration_does_not_change_manual_queue_or_relevance_preferences(self):
        preferences = Preferences(categories=['BPC'], hide_closed=False)
        self.repo.save_preferences(preferences)
        self.assertEqual(self.update(self.read(),enabled=True)[0],200)
        self.assertEqual(self.repo.get_preferences(),preferences)
        job_id,_ = self.queue.enqueue()
        jobs.execute_job(self.queue,*self.queue.claim(),adapters={self.source.adapter:self.adapter})
        self.assertEqual(self.queue.get(job_id)['status'],'succeeded')

    def test_upgrade_preserves_existing_data_and_automation_repeated_migration(self):
        directory = Path(self.temp.name) / 'old_migrations'
        directory.mkdir()
        for file in MIGRATIONS.glob('*.sql'):
            if file.name < '004':
                shutil.copy2(file,directory)
        path = Path(self.temp.name) / 'upgrade.db'
        old = Database(path,directory)
        old.migrate()
        repo = Repository(old)
        preferences = Preferences(categories=['BCC'], hide_closed=False)
        repo.save_preferences(preferences)
        saved = repo.create_competition(self.adapter.return_value.data)
        upgraded = Database(path)
        self.assertEqual(upgraded.migrate(),['004','005'])
        self.assertEqual(Repository(upgraded).get_preferences(),preferences)
        self.assertEqual(Repository(upgraded).get_competition(saved.id),saved)
        store = AutomationStore(upgraded)
        store.save(AutomationSettings(enabled=True),expected_version=1)
        self.assertEqual(upgraded.migrate(),[])
        self.assertTrue(store.get()['settings'].enabled)
