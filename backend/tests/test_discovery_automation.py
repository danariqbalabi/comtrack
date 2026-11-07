import json
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit

from backend.app.automation import AutomationSettings,AutomationStore
from backend.app.collectors import discovery as collector
from backend.app.collectors.http import Page,FetchError
from backend.app.config import Settings
from backend.app.database import Database,MIGRATIONS
from backend.app.discovery import DiscoveryBlocked,DiscoveryContext,query_pool,normalize_candidate
from backend.app.discovery_api import router,summary
from backend.app.job_queue import JobQueue,LostLeaseError,SourceDisabledError
from backend.app.models import Preferences
from backend.app.repository import Repository
from backend.app.scheduler import Scheduler
from backend.app.worker import execute_job
from backend.tests import test_jobs as jobs
from backend.tests.test_public_sources import HTML
from backend.tests.test_collection import fixture_page


class DiscoveryAutomationTests(unittest.TestCase):
    setUp=jobs.QueueTests.setUp
    tearDown=jobs.QueueTests.tearDown
    request=jobs.ApiTests.request
    routers=(router,)
    protect=True

    def setup_discovery(self,*,free=False,**limits):
        if not free:self.repo.set_source_enabled(self.source.id,False)
        self.repo.save_preferences(Preferences(categories=['BPC'],discovery_enabled=True))
        self.store=AutomationStore(self.database)
        self.store.save(AutomationSettings(enabled=True,allow_paid_providers=True,provider_daily_request_limit=10,
            provider_daily_budget_usd='0.10',**limits),expected_version=1)
        job_id=Scheduler(self.database).tick()['job_id']
        source=next(row for row in self.queue.pending_sources(job_id) if row['adapter']=='brave_discovery')
        _,token=self.queue.claim()
        self.job_id,self.token,self.discovery_source=job_id,token,source
        self.context=DiscoveryContext(self.queue,job_id,token,source)
        self.config=Settings(_env_file=None,discovery_provider_enabled=True,brave_api_key='fixture-secret-key',brave_cost_per_request_usd='0.001')
        self.client=Mock();self.client.get.side_effect=lambda url: Page(url,HTML,'text/html')

    def collect(self,hits=None):
        if hits is None:hits=[{'url':'https://example.com/event?utm_source=search','title':'Search title is not an extracted fact','description':'Fake snippet deadline 2099'}]
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value={'web':{'results':hits}}) as search,patch.object(collector.time,'sleep'):
            batch=collector.collect(self.queue,self.job_id,self.token,self.discovery_source,client=self.client)
        return batch,search

    def candidates(self):
        return self.request('GET','/api/discovery/candidates')[1]['items']

    def test_query_plan_uses_preferences_and_persists_rotation(self):
        self.setup_discovery()
        first=self.context.queries
        self.assertTrue(all('business plan' in query.lower() for query in first))
        self.assertFalse(any('hackathon' in query for query in first))
        self.assertTrue(any('mahasiswa' in query for query in first))
        self.queue.finish(self.job_id,self.token,cancelled=True)
        with self.database.transaction() as conn:conn.execute("UPDATE automation_schedule SET next_run_at='2000-01-01T00:00:00+00:00'")
        next_job=Scheduler(Database(self.database.path)).tick()['job_id']
        with self.database.connection() as conn:
            second=json.loads(conn.execute('SELECT queries_json FROM discovery_plans JOIN collection_job_sources s ON s.id=job_source_id WHERE s.job_id=?',(next_job,)).fetchone()[0])
        self.assertNotEqual(first,second)
        self.assertEqual(len(first),3)
        pool=query_pool(Preferences(categories=['hackathon'],education_level='any'),2030)
        self.assertTrue(all('2030' in query for query in pool))
        self.assertFalse(any('mahasiswa' in query or 'university students' in query for query in pool))

    def test_response_contract_fixed_endpoint_and_header_auth_helper(self):
        self.setup_discovery()
        _,search=self.collect()
        host,path=search.call_args.args
        self.assertEqual(host,'api.search.brave.com')
        params=parse_qs(urlsplit(path).query)
        self.assertEqual(params['country'],['ID'])
        self.assertEqual(params['search_lang'],['id'])
        self.assertEqual(params['result_filter'],['web'])
        self.assertNotIn('fixture-secret-key',path)
        self.assertTrue(search.call_args.kwargs['brave'])

    def test_snippets_never_become_competition_facts_and_tracking_hits_deduplicate(self):
        self.setup_discovery()
        batch,_=self.collect([{'url':'https://example.com/event?utm_source=one','title':'Fake search title'},
                              {'url':'https://example.com/event?utm_source=two','title':'Other title'}])
        self.assertEqual(len(batch.items),1)
        self.assertIn('Fixture Business Plan',batch.items[0].data.name)
        self.assertNotIn('Fake search title',batch.items[0].raw_text)
        self.assertEqual(len(self.candidates()),1)
        self.assertEqual(self.candidates()[0]['domain'],'example.com')
        self.assertEqual(self.candidates()[0]['status'],'verified')
        self.assertEqual(len(self.repo.list_sources()),2) # existing fixture + virtual search; candidate domain not subscribed
        self.assertEqual(self.repo.list_competitions(),[])

    def test_missing_credentials_or_estimate_never_call_search(self):
        self.setup_discovery()
        for config in (Settings(_env_file=None),Settings(_env_file=None,discovery_provider_enabled=True,brave_api_key='fixture')):
            with patch.object(collector,'get_settings',return_value=config),patch.object(collector.providers,'request_json') as search:
                with self.assertRaises(ValueError):collector.collect(self.queue,self.job_id,self.token,self.discovery_source)
                search.assert_not_called()

    def test_missing_paid_permission_blocks_before_reserving_or_calling(self):
        self.setup_discovery()
        state=self.store.get()
        self.store.save(state['settings'].model_copy(update={'allow_paid_providers':False}),expected_version=state['version'])
        batch,search=self.collect()
        search.assert_not_called()
        self.assertTrue(batch.errors)
        with self.database.connection() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM provider_request_reservations').fetchone()[0],0)

    def test_daily_request_and_estimated_budget_caps_enforced_atomically(self):
        self.setup_discovery()
        state=self.store.get()
        self.store.save(state['settings'].model_copy(update={'provider_daily_request_limit':1}),expected_version=state['version'])
        def reserve(index):
            try:
                self.context.reserve(index,self.context.queries[index],Decimal('0.01'));return True
            except DiscoveryBlocked:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(reserve,(0,1))),1)
        with self.database.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*),sum(reserved_microusd) FROM provider_request_reservations').fetchone()[1],10000)

    def test_cost_that_exceeds_budget_is_blocked_and_utc_day_rolls_over(self):
        self.setup_discovery()
        with self.assertRaises(DiscoveryBlocked):self.context.reserve(0,self.context.queries[0],Decimal('0.11'))
        day=datetime(2030,1,1,23,59,tzinfo=timezone.utc)
        self.context.reserve(0,self.context.queries[0],Decimal('0.10'),now=day)
        with self.assertRaises(DiscoveryBlocked):self.context.reserve(1,self.context.queries[1],Decimal('0.01'),now=day)
        self.context.reserve(1,self.context.queries[1],Decimal('0.01'),now=day+timedelta(minutes=2))

    def test_crashed_reserved_request_is_not_sent_again(self):
        self.setup_discovery()
        self.context.reserve(0,self.context.queries[0],Decimal('0.001'))
        batch,search=self.collect()
        search.assert_not_called()
        self.assertTrue(batch.errors)

    def test_successful_query_results_reused_after_restart_without_more_search_cost(self):
        self.setup_discovery()
        first,search=self.collect()
        self.assertEqual(search.call_count,3)
        self.context=DiscoveryContext(JobQueue(Database(self.database.path)),self.job_id,self.token,self.discovery_source)
        second,search=self.collect()
        search.assert_not_called()
        self.assertEqual(second.activity['queries_reused'],3)
        self.assertEqual(len(self.candidates()),1)

    def test_failed_request_stops_remaining_queries_without_refund(self):
        self.setup_discovery()
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',side_effect=ValueError('Provider failure')) as search:
            batch=collector.collect(self.queue,self.job_id,self.token,self.discovery_source)
        search.assert_called_once()
        self.assertTrue(batch.errors)
        with self.database.connection() as conn:
            row=conn.execute('SELECT status,reserved_microusd FROM provider_request_reservations').fetchone()
            self.assertEqual(tuple(row),('failed',1000))

    def test_private_urls_rejected_and_social_media_candidates_not_scraped(self):
        self.setup_discovery()
        batch,_=self.collect([{'url':url,'title':'Candidate'} for url in ('http://127.0.0.1/','file:///secret','http://10.0.0.2/','https://www.instagram.com/lombabisnis/')])
        self.client.get.assert_not_called()
        self.assertEqual(batch.items,[])
        self.assertEqual(len(self.candidates()),1)
        self.assertEqual(self.candidates()[0]['status'],'unverified')

    def test_verification_page_budget_preserves_unvisited_candidates(self):
        self.setup_discovery(max_pages_per_source=1)
        batch,_=self.collect([{'url':f'https://example.com/{index}','title':'Candidate'} for index in range(4)])
        self.client.get.assert_called_once()
        self.assertEqual(len(self.candidates()),4)
        self.assertEqual(sum(row['status']=='unverified' for row in self.candidates()),3)

    def test_unreadable_page_retains_candidate_without_ingesting_snippet(self):
        self.setup_discovery()
        self.client.get.side_effect=FetchError('HTTP 403')
        batch,_=self.collect()
        self.assertEqual(batch.items,[])
        self.assertEqual(self.candidates()[0]['status'],'failed')

    def test_pause_and_stale_worker_cannot_reserve_search_requests(self):
        self.setup_discovery()
        with self.database.transaction() as conn:conn.execute("UPDATE collection_jobs SET lease_expires_at='2000-01-01'")
        self.queue.claim()
        with self.assertRaises(LostLeaseError):self.context.reserve(0,self.context.queries[0],Decimal('0.01'))

    def test_discovery_preference_revoked_stops_before_search(self):
        self.setup_discovery()
        self.repo.save_preferences(Preferences(discovery_enabled=False))
        with self.assertRaises(SourceDisabledError):self.collect()

    def test_existing_website_survives_search_failure(self):
        self.setup_discovery(free=True)
        def get(url):
            return fixture_page() if 'ou-festival.com' in url else Page(url,HTML,'text/html')
        self.client.get.side_effect=get
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',side_effect=ValueError('Provider failure')):
            execute_job(self.queue,self.job_id,self.token,client=self.client)
        self.assertEqual(len(self.repo.list_competitions()),1)
        self.assertEqual(self.queue.get(self.job_id)['status'],'partial')

    def test_scheduler_search_to_original_article_to_feed_persistent_end_to_end(self):
        self.setup_discovery()
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value={'web':{'results':[{'url':'https://example.com/event','title':'Search title'}]}}),patch.object(collector.time,'sleep'):
            execute_job(self.queue,self.job_id,self.token,client=self.client)
        self.assertEqual(self.queue.get(self.job_id)['status'],'succeeded')
        self.assertEqual(len(Repository(Database(self.database.path)).list_competitions()),1)
        self.assertEqual(self.repo.list_evidence(1)[0]['url'],'https://example.com/event')
        self.assertEqual(self.candidates()[0]['status'],'verified')

    def test_activity_and_paginated_filters_do_not_expose_credentials(self):
        self.setup_discovery();self.collect()
        with patch('backend.app.discovery_api.get_settings',return_value=self.config):
            status,body=self.request('GET','/api/discovery')
        self.assertEqual(status,200)
        self.assertEqual(body['budget']['requests_reserved'],3)
        self.assertNotIn('fixture-secret',json.dumps(body))
        self.assertEqual(self.request('GET','/api/discovery/candidates?status=failed')[1]['total'],0)
        self.assertEqual(self.request('GET','/api/discovery/candidates?domain=example.com')[1]['total'],1)
        self.assertEqual(self.request('GET','/api/discovery/candidates?offset=-1')[0],422)

    def test_legacy_candidates_and_preferences_survive_upgrade(self):
        directory=Path(self.temp.name)/'old';directory.mkdir()
        for file in MIGRATIONS.glob('*.sql'):
            if file.name<'006':shutil.copy2(file,directory)
        path=Path(self.temp.name)/'old.db';old=Database(path,directory);old.migrate()
        with old.transaction() as conn:
            conn.execute("INSERT INTO discovery_candidates(url,title,status,first_seen_at,last_seen_at) VALUES ('https://example.com/old','Old','unverified','2030-01-01','2030-01-01')")
        upgraded=Database(path);self.assertEqual(upgraded.migrate(),['006'])
        with upgraded.connection() as conn:self.assertEqual(conn.execute('SELECT title FROM discovery_candidates').fetchone()[0],'Old')

    def test_blank_estimate_is_unconfigured_and_invalid_precision_rejected(self):
        self.assertIsNone(Settings(_env_file=None,brave_cost_per_request_usd='').brave_cost_per_request_usd)
        for value in ('0','-1','NaN','0.0000001'):
            with self.subTest(value=value),self.assertRaises(ValueError):Settings(_env_file=None,brave_cost_per_request_usd=value)

    def test_malformed_search_response_stops_and_does_not_fabricate_hits(self):
        self.setup_discovery()
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value={'web':{'results':None}}) as search:
            batch=collector.collect(self.queue,self.job_id,self.token,self.discovery_source)
        search.assert_called_once()
        self.assertTrue(batch.errors)
        self.assertEqual(self.candidates(),[])

    def test_cached_verification_preserves_prior_checked_status_when_pages_run_out(self):
        self.setup_discovery(max_pages_per_source=1)
        self.collect()
        first=self.candidates()[0]
        self.collect()
        second=self.candidates()[0]
        self.assertEqual(second['status'],'verified')
        self.assertEqual(second['checked_at'],first['checked_at'])

    def test_known_failure_or_empty_extraction_never_creates_feed_items(self):
        self.setup_discovery()
        self.client.get.side_effect=lambda url:Page(url,b'<main><h1>Seminar umum</h1><article>Bukan kompetisi</article></main>','text/html')
        batch,_=self.collect()
        self.assertEqual(batch.items,[])
        self.assertEqual(self.candidates()[0]['status'],'irrelevant')

    def test_discovery_cannot_exceed_source_cap_or_create_unmonitored_domains(self):
        self.setup_discovery()
        self.queue.finish(self.job_id,self.token,cancelled=True)
        source_id=self.discovery_source['source_id']
        self.repo.delete_source(source_id)
        from backend.app.models import SourceData
        for index in range(29):
            self.repo.create_source(SourceData(name=f'Fixture {index}',kind='website',url=f'https://example.com/{index}',adapter='unsupported'))
        with self.database.transaction() as conn:conn.execute("UPDATE automation_schedule SET next_run_at='2000-01-01T00:00:00+00:00'")
        Scheduler(self.database).tick()
        self.assertEqual(len(self.repo.list_sources()),30)
        with patch('backend.app.discovery_api.get_settings',return_value=self.config):
            self.assertEqual(summary(self.repo)['state'],'source_limit')
