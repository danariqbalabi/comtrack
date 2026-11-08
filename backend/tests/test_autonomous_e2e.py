"""Full pipeline with explicit provider fixtures; never creates demo data in the user's DB."""
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from backend.app import extraction,onboarding
from backend.app.automation import AutomationStore
from backend.app.collectors import discovery as collector,providers
from backend.app.collectors.http import Page
from backend.app.config import Settings
from backend.app.job_queue import LostLeaseError
from backend.app.scheduler import Scheduler
from backend.app.worker import execute_job,ADAPTERS
from backend.tests import test_discovery_automation as helpers

NAME='Fixture Integrated Business Plan Competition 2030'
CAPTION=NAME+'\nKompetisi nasional Indonesia untuk mahasiswa\nPendaftaran: 22 November 2030\nBiaya: gratis\nDaftar: https://forms.gle/integrated-fixture'
HTML=('<main><h1>'+NAME+'</h1><article><p>Kompetisi nasional Indonesia untuk mahasiswa</p><p>Pendaftaran: 22 November 2030</p><p>Biaya: gratis</p><a href="https://forms.gle/integrated-fixture">Daftar sekarang</a><a href="https://instagram.com/lombafixture/">Instagram</a></article></main>').encode()
PROFILE={'username':'lombafixture','private':False,'biography':'Media informasi lomba untuk mahasiswa Indonesia'}
POST={'url':'https://www.instagram.com/p/INTEGRATED/','ownerUsername':'lombafixture','caption':CAPTION}


class AutonomousEndToEndTests(unittest.TestCase):
    tearDown=helpers.DiscoveryAutomationTests.tearDown

    def setUp(self):
        helpers.DiscoveryAutomationTests.setUp(self)
        helpers.DiscoveryAutomationTests.setup_discovery(self)
        self.config=Settings(_env_file=None,discovery_provider_enabled=True,discovery_provider='brave',brave_api_key='fixture-brave',brave_cost_per_request_usd='0.001',
            instagram_provider_enabled=True,apify_token='fixture-apify',apify_max_charge_usd=.01)
        self.client.get.side_effect=lambda url:Page(url,HTML,'text/html')
        self.calls={'brave':0,'profiles':0,'posts':0}

    def provider(self,host,path,**kwargs):
        if host=='api.search.brave.com':
            self.calls['brave']+=1
            return {'web':{'results':[{'url':'https://example.com/competition','title':'Fixture search result'}]}}
        if 'instagram-profile-scraper' in path:
            self.calls['profiles']+=1;return [PROFILE]
        self.calls['posts']+=1;return [POST]

    def run_job(self,job,token):
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(extraction,'get_settings',return_value=self.config),patch.object(providers,'request_json',side_effect=self.provider),patch.object(collector.time,'sleep'):
            return execute_job(self.queue,job,token,client=self.client,propagate_errors=True)

    def test_discovery_onboards_web_and_account_then_next_job_deduplicates_both(self):
        self.run_job(self.job_id,self.token)
        self.assertEqual(self.calls,{'brave':3,'profiles':1,'posts':0})
        self.assertEqual(len(self.repo.list_competitions()),1)
        sources=self.repo.list_sources()
        self.assertEqual(sum(source.adapter=='discovered_article' for source in sources),1)
        self.assertEqual(sum(source.kind=='instagram' for source in sources),1)
        self.repo.set_source_enabled(self.discovery_source['source_id'],False)
        next_job=Scheduler(self.database).tick(now=datetime.now(timezone.utc)+timedelta(days=1))['job_id']
        _,token=self.queue.claim()
        self.run_job(next_job,token)
        self.assertEqual(self.calls['posts'],1)
        self.assertEqual(len(self.repo.list_competitions()),1)
        record=self.repo.list_competitions()[0]
        self.assertEqual(record.data.relevance_status,'relevant',record.data.relevance_reasons)
        self.assertFalse(record.data.conflicts,record.data.conflicts)
        self.assertGreaterEqual(len(self.repo.list_evidence(record.id)),2)
        with self.database.connection() as conn:self.assertFalse(conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_recovery_after_ingest_before_onboarding_reuses_search_and_evidence(self):
        with patch.object(onboarding,'qualify',side_effect=LostLeaseError('fixture crash after ingest')):
            with self.assertRaises(LostLeaseError):self.run_job(self.job_id,self.token)
        self.assertEqual(len(self.repo.list_competitions()),1)
        original=self.repo.list_competitions()[0]
        with self.database.transaction() as conn:conn.execute("UPDATE collection_jobs SET lease_expires_at='2000-01-01' WHERE id=?",(self.job_id,))
        recovered,token=self.queue.claim()
        self.assertEqual(recovered,self.job_id)
        self.run_job(recovered,token)
        self.assertEqual(self.calls['brave'],3)
        self.assertEqual(self.calls['profiles'],1)
        self.assertEqual(self.queue.get(recovered)['attempts'],2)
        self.assertEqual(len(self.repo.list_competitions()),1)
        self.assertEqual(len(self.repo.list_evidence(original.id)),1)
        self.assertEqual(sum(s.adapter=='discovered_article' for s in self.repo.list_sources()),1)

    def manual_job(self):
        self.queue.finish(self.job_id,self.token,cancelled=True)
        store=AutomationStore(self.database);state=store.get()
        store.save(state['settings'].model_copy(update={'enabled':False,'provider_daily_request_limit':1}),expected_version=state['version'])
        job,_=self.queue.enqueue([self.discovery_source['source_id']]);_,token=self.queue.claim()
        return job,token

    def test_manual_refresh_shares_quota_but_keeps_manual_trigger_and_no_auto_onboarding(self):
        job,token=self.manual_job();self.run_job(job,token)
        self.assertEqual(self.calls,{'brave':1,'profiles':0,'posts':0})
        self.assertEqual(self.queue.get(job)['trigger'],'manual')
        self.assertIsNone(self.queue.automation_settings(job))
        self.assertIsNotNone(self.queue.collection_settings(job))
        self.assertEqual(len(self.repo.list_sources()),2)
        self.assertEqual(len(self.repo.list_competitions()),1)

    def test_manual_permission_cannot_be_raised_after_job_is_queued(self):
        self.queue.finish(self.job_id,self.token,cancelled=True)
        store=AutomationStore(self.database);state=store.get()
        store.save(state['settings'].model_copy(update={'enabled':False,'allow_paid_providers':False}),expected_version=state['version'])
        job,_=self.queue.enqueue([self.discovery_source['source_id']])
        state=store.get();store.save(state['settings'].model_copy(update={'allow_paid_providers':True}),expected_version=state['version'])
        _,token=self.queue.claim();self.run_job(job,token)
        self.assertEqual(self.calls['brave'],0)

    def test_manual_website_collection_also_respects_persistent_page_limit(self):
        from backend.app.models import SourceData
        from unittest.mock import Mock
        self.queue.finish(self.job_id,self.token,cancelled=True)
        store=AutomationStore(self.database);state=store.get()
        store.save(state['settings'].model_copy(update={'max_pages_per_source':1}),expected_version=state['version'])
        source=self.repo.create_source(SourceData(name='Fixture listing',kind='website',url='https://example.com/list',adapter='public_html',config={'links_selector':'a'}))
        job,_=self.queue.enqueue([source.id]);_,token=self.queue.claim()
        client=Mock();client.get.return_value=Page(str(source.url),b'<a href="/competition">Business Plan Competition</a>','text/html')
        execute_job(self.queue,job,token,client=client)
        client.get.assert_called_once()
        self.assertEqual(self.repo.list_competitions(),[])
        self.assertEqual(self.queue.get(job)['sources'][0]['result']['page_budget']['used'],1)

    def test_free_source_survives_missing_search_credentials(self):
        self.queue.finish(self.job_id,self.token,cancelled=True)
        self.repo.set_source_enabled(self.source.id,True)
        with self.database.transaction() as conn:conn.execute("UPDATE automation_schedule SET next_run_at='2000-01-01T00:00:00+00:00'")
        job=Scheduler(self.database).tick()['job_id'];_,token=self.queue.claim()
        with patch.object(collector,'get_settings',return_value=Settings(_env_file=None)),patch.object(providers,'request_json',side_effect=AssertionError('paid call')):
            execute_job(self.queue,job,token,adapters={**ADAPTERS,self.source.adapter:self.adapter})
        self.assertEqual(self.queue.get(job)['status'],'partial')
        self.assertEqual(len(self.repo.list_competitions()),1)

    def test_pause_prevents_new_discovery_accounts_and_facts(self):
        store=AutomationStore(self.database);state=store.get()
        store.save(state['settings'].model_copy(update={'enabled':False}),expected_version=state['version'])
        with patch.object(providers,'request_json',side_effect=AssertionError('paid call')):execute_job(self.queue,self.job_id,self.token,client=self.client)
        self.assertEqual(self.repo.list_competitions(),[])
        self.assertEqual(len(self.repo.list_sources()),2)
