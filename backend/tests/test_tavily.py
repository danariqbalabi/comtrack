import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from backend.app import tavily_budget
from backend.app.automation import AutomationStore,AutomationSettings
from backend.app.collectors import discovery as collector
from backend.app.config import Settings
from backend.app.discovery import DiscoveryContext,DiscoveryBlocked
from backend.app.discovery_api import summary
from backend.app.job_queue import SourceDisabledError,LostLeaseError
from backend.app.scheduler import Scheduler
from backend.app.worker import execute_job
from backend.tests import test_discovery_automation as helpers

HITS={'results':[{'url':'https://example.com/event','title':'Search title','content':'Do not use this snippet as a fact'}],'usage':{'credits':1}}


class TavilyTests(unittest.TestCase):
    tearDown=helpers.DiscoveryAutomationTests.tearDown

    def setUp(self):
        helpers.DiscoveryAutomationTests.setUp(self)
        helpers.DiscoveryAutomationTests.setup_discovery(self)
        self.queue.finish(self.job_id,self.token,cancelled=True)
        self.update(allow_paid_providers=False,provider_daily_request_limit=0,provider_daily_budget_usd='0.00')
        with self.database.transaction() as conn:conn.execute("UPDATE automation_schedule SET next_run_at='2000-01-01T00:00:00+00:00'")
        self.job_id=Scheduler(self.database).tick()['job_id'];_,self.token=self.queue.claim()
        self.discovery_source=self.queue.pending_sources(self.job_id)[0]
        self.context=DiscoveryContext(self.queue,self.job_id,self.token,self.discovery_source)
        self.config=Settings(_env_file=None,discovery_provider_enabled=True,tavily_api_key='fixture-tavily-secret')

    def update(self,**changes):
        store=AutomationStore(self.database);state=store.get()
        values={**state['settings'].model_dump(mode='json'),**changes}
        return store.save(AutomationSettings.model_validate(values),expected_version=state['version'])

    def collect(self,response=HITS):
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value=response) as request,patch.object(collector.time,'sleep'):
            batch=collector.collect(self.queue,self.job_id,self.token,self.discovery_source,client=self.client)
        return batch,request

    def test_basic_contract_and_pipeline_work_without_paid_permission_or_brave_key(self):
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value=HITS) as request,patch.object(collector.time,'sleep'):
            execute_job(self.queue,self.job_id,self.token,client=self.client,propagate_errors=True)
        self.assertEqual(request.call_count,3)
        host,path=request.call_args.args;payload=request.call_args.kwargs['payload']
        self.assertEqual((host,path),('api.tavily.com','/search'))
        self.assertEqual(payload['search_depth'],'basic');self.assertFalse(payload['auto_parameters'])
        self.assertEqual(payload['country'],'indonesia');self.assertFalse(payload['include_answer'])
        self.assertFalse(payload['include_raw_content']);self.assertEqual(payload['max_results'],5)
        self.assertNotIn('fixture-tavily-secret',path);self.assertNotIn('api_key',payload)
        self.assertEqual(len(self.repo.list_competitions()),1)
        self.assertNotIn('Do not use this snippet',self.repo.list_competitions()[0].data.summary)
        self.assertTrue(any(s.adapter=='discovered_article' for s in self.repo.list_sources()))
        with self.database.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM provider_request_reservations').fetchone()[0],0)
            self.assertEqual(tavily_budget.usage(conn)['monthly_reserved'],3)

    def test_missing_tavily_key_does_not_fall_back_to_brave(self):
        self.config=self.config.model_copy(update={'tavily_api_key':Settings(_env_file=None).tavily_api_key})
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json') as request:
            with self.assertRaises(collector.providers.ProviderUnavailable):collector.collect(self.queue,self.job_id,self.token,self.discovery_source)
            request.assert_not_called()

    def test_daily_limit_applies_without_spending_usd(self):
        self.update(tavily_daily_credit_limit=1)
        batch,request=self.collect()
        request.assert_called_once();self.assertTrue(any('harian' in error for error in batch.errors))
        self.assertEqual(len(batch.items),1)

    def test_manual_and_scheduled_search_share_free_credits(self):
        self.update(tavily_daily_credit_limit=4)
        _,first=self.collect();self.assertEqual(first.call_count,3)
        self.queue.finish(self.job_id,self.token,cancelled=True)
        self.job_id,_=self.queue.enqueue([self.discovery_source['source_id']]);_,self.token=self.queue.claim()
        self.discovery_source=self.queue.pending_sources(self.job_id)[0]
        self.context=DiscoveryContext(self.queue,self.job_id,self.token,self.discovery_source)
        _,second=self.collect();second.assert_called_once()
        self.assertEqual(self.queue.get(self.job_id)['trigger'],'manual')
        with self.database.connection() as conn:self.assertEqual(tavily_budget.usage(conn)['daily_reserved'],4)

    def test_monthly_limit_does_not_reset_on_new_day_but_resets_next_month(self):
        self.update(tavily_monthly_credit_limit=1)
        now=datetime(2030,1,30,tzinfo=timezone.utc)
        self.assertIsNone(tavily_budget.reserve(self.context,0,self.context.queries[0],now=now))
        with self.assertRaises(DiscoveryBlocked):tavily_budget.reserve(self.context,1,self.context.queries[1],now=now+timedelta(days=1))
        self.assertIsNone(tavily_budget.reserve(self.context,1,self.context.queries[1],now=datetime(2030,2,1,tzinfo=timezone.utc)))

    def test_daily_limit_resets_next_utc_day(self):
        self.update(tavily_daily_credit_limit=1)
        now=datetime(2030,1,1,23,59,tzinfo=timezone.utc)
        tavily_budget.reserve(self.context,0,self.context.queries[0],now=now)
        self.assertIsNone(tavily_budget.reserve(self.context,1,self.context.queries[1],now=now+timedelta(minutes=2)))

    def test_parallel_reservations_cannot_exceed_limit(self):
        self.update(tavily_daily_credit_limit=1)
        def reserve(index):
            try:tavily_budget.reserve(self.context,index,self.context.queries[index]);return True
            except DiscoveryBlocked:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(reserve,[0,1])),1)

    def test_crash_and_provider_failure_do_not_resend_request(self):
        tavily_budget.reserve(self.context,0,self.context.queries[0])
        recovered=DiscoveryContext(self.queue,self.job_id,self.token,self.discovery_source)
        with self.assertRaises(DiscoveryBlocked):tavily_budget.reserve(recovered,0,recovered.queries[0])
        tavily_budget.finish(self.context,0)
        with self.assertRaises(DiscoveryBlocked):tavily_budget.reserve(recovered,0,recovered.queries[0])

    def test_successful_cached_response_does_not_reserve_again(self):
        tavily_budget.reserve(self.context,0,self.context.queries[0]);tavily_budget.finish(self.context,0,HITS['results'])
        self.assertEqual(tavily_budget.reserve(self.context,0,self.context.queries[0]),HITS['results'])
        with self.database.connection() as conn:self.assertEqual(tavily_budget.usage(conn)['daily_reserved'],1)

    def test_provider_switch_mid_job_is_blocked(self):
        tavily_budget.reserve(self.context,0,self.context.queries[0])
        with self.assertRaises(DiscoveryBlocked):tavily_budget.pin(self.context,'brave')
        with self.assertRaises(DiscoveryBlocked):self.context.reserve(1,self.context.queries[1],helpers.Decimal('.001'))

    def test_zero_limit_pause_and_stale_token_make_no_request(self):
        self.update(tavily_daily_credit_limit=0)
        batch,request=self.collect();request.assert_not_called();self.assertTrue(batch.errors)
        self.update(tavily_daily_credit_limit=20,tavily_free_enabled=False)
        with self.assertRaises(SourceDisabledError):tavily_budget.authorize(self.context)
        self.context.token='stale'
        with self.assertRaises(LostLeaseError):tavily_budget.reserve(self.context,0,self.context.queries[0])

    def test_credit_contract_change_persistently_blocks_future_requests(self):
        _,request=self.collect({**HITS,'usage':{'credits':2}});request.assert_called_once()
        _,again=self.collect();again.assert_not_called()
        with patch('backend.app.discovery_api.get_settings',return_value=self.config):self.assertEqual(summary(self.repo)['state'],'contract_changed')

    def test_snapshot_limit_cannot_be_raised_mid_job(self):
        self.context.snapshot=self.context.snapshot.model_copy(update={'tavily_monthly_credit_limit':0})
        with self.assertRaises(DiscoveryBlocked):tavily_budget.reserve(self.context,0,self.context.queries[0])

    def test_api_reports_free_ready_with_paid_permission_off_and_no_secret(self):
        with patch('backend.app.discovery_api.get_settings',return_value=self.config):body=summary(self.repo)
        self.assertEqual(body['provider'],'tavily');self.assertEqual(body['state'],'ready')
        self.assertEqual(body['free_budget']['monthly_limit'],600)
        self.assertNotIn('fixture-tavily-secret',json.dumps(body))

    def test_integration_panels_recognize_tavily_key_without_brave(self):
        from backend.app.settings_api import integrations
        from backend.app.automation_api import present
        store=AutomationStore(self.database)
        with patch('backend.app.config.get_settings',return_value=self.config):self.assertTrue(integrations()['discovery'])
        with patch('backend.app.automation_api.get_settings',return_value=self.config):result=present(store.get(),store.schedule())
        self.assertTrue(result['runtime']['providers']['discovery']['automation_allowed'])
        self.assertEqual(result['runtime']['providers']['discovery']['provider'],'tavily')

    def test_invalid_limits_are_rejected(self):
        for changes in ({'tavily_monthly_credit_limit':1001},{'tavily_daily_credit_limit':-1},{'tavily_free_enabled':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):AutomationSettings(**changes)

    def test_missing_usage_is_not_assumed_to_cost_one_credit(self):
        self.collect({'results':[]})
        with self.database.connection() as conn:self.assertEqual(conn.execute('SELECT blocked FROM tavily_safety').fetchone()[0],1)

    def test_upgrade_preserves_and_pins_existing_brave_reservation(self):
        import shutil
        from pathlib import Path
        from backend.app.database import Database,MIGRATIONS
        from backend.app.job_queue import JobQueue
        from backend.app.repository import Repository
        from backend.app.models import SourceData,Preferences
        directory=Path(self.temp.name)/'old-migrations';directory.mkdir()
        for file in MIGRATIONS.glob('*.sql'):
            if file.name<'012':shutil.copy2(file,directory)
        old=Database(Path(self.temp.name)/'legacy.db',directory);old.migrate()
        repo=Repository(old);repo.save_preferences(Preferences(discovery_enabled=True))
        source=repo.create_source(SourceData(name='Legacy discovery',kind='website',url='https://api.search.brave.com/',adapter='brave_discovery'))
        queue=JobQueue(old);job,_=queue.enqueue([source.id]);job_source=queue.pending_sources(job)[0]
        with old.transaction() as conn:
            conn.execute("INSERT INTO provider_request_reservations(job_source_id,query_index,query_text,provider,day_utc,reserved_microusd,status,created_at) VALUES (?,0,'legacy','brave','2030-01-01',1000,'reserved','2030-01-01')",(job_source['id'],))
        upgraded=Database(old.path);self.assertEqual(upgraded.migrate(),['012'])
        with upgraded.connection() as conn:
            self.assertEqual(conn.execute('SELECT provider FROM discovery_provider_runs').fetchone()[0],'brave')
            self.assertEqual(conn.execute('SELECT count(*) FROM provider_request_reservations').fetchone()[0],1)
