import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from backend.app.automation import AutomationStore
from backend.app.collectors import discovery as collector
from backend.app.collectors.discovered import collect as monitor
from backend.app.collectors.http import Page
from backend.app.job_queue import LostLeaseError, SourceDisabledError
from backend.app.models import EvidenceData, SourceData
from backend.app.onboarding import qualify
from backend.app.quality.service import ingest
from backend.app.scheduler import Scheduler
from backend.app.worker import execute_job
from backend.tests import test_discovery_automation as helpers
from backend.tests.test_public_sources import HTML


class OnboardingTests(unittest.TestCase):
    setUp=helpers.DiscoveryAutomationTests.setUp
    tearDown=helpers.DiscoveryAutomationTests.tearDown
    setup_discovery=helpers.DiscoveryAutomationTests.setup_discovery
    collect=helpers.DiscoveryAutomationTests.collect
    candidates=helpers.DiscoveryAutomationTests.candidates
    request=helpers.DiscoveryAutomationTests.request
    routers=helpers.DiscoveryAutomationTests.routers
    protect=True

    def observation(self, **changes):
        batch,_=self.collect()
        item=batch.items[0]
        if changes:
            item=replace(item,data=item.data.model_copy(update=changes))
        saved,_=ingest(self.repo,item.data,EvidenceData(fetched_at=datetime.now(timezone.utc),source_id=self.discovery_source['source_id'],
            url=item.data.source_url,content_hash=item.content_hash,raw_text=item.raw_text,field_values=item.field_values))
        return item,saved,next(iter(batch.onboarding_keys.values()))

    def qualify(self, observation):
        return qualify(self.queue,self.job_id,self.token,self.discovery_source,*observation)

    def update_settings(self, **changes):
        store=AutomationStore(self.database);value=store.get()
        store.save(value['settings'].model_copy(update=changes),expected_version=value['version'])

    def test_register_once_with_stored_decision_and_no_current_job_expansion(self):
        self.setup_discovery()
        observation=self.observation()
        result=self.qualify(observation)
        self.assertEqual(result['status'],'active')
        self.assertEqual(self.qualify(observation)['status'],'existing')
        added=next(s for s in self.repo.list_sources() if s.id==result['source_id'])
        self.assertEqual(added.adapter,'discovered_article')
        self.assertTrue(added.enabled)
        self.assertNotIn(added.id,[s['source_id'] for s in self.queue.pending_sources(self.job_id)])
        candidate=self.candidates()[0]
        self.assertEqual(candidate['onboarded_source_id'],added.id)
        self.assertTrue(candidate['onboarding_reason'])

    def test_successful_worker_onboards_then_next_job_monitors_article(self):
        self.setup_discovery()
        hits=[{'url':'https://example.com/event','title':'Search result'}]
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value={'web':{'results':hits}}),patch.object(collector.time,'sleep'):
            execute_job(self.queue,self.job_id,self.token,client=self.client,propagate_errors=True)
        added=next(s for s in self.repo.list_sources() if s.adapter=='discovered_article')
        result=next(s for s in self.queue.get(self.job_id)['sources'] if s['adapter']=='brave_discovery')
        self.assertEqual(result['result']['onboarding'][0]['status'],'active')
        self.repo.set_source_enabled(self.discovery_source['source_id'],False)
        with self.database.transaction() as conn:
            conn.execute("UPDATE automation_schedule SET next_run_at='2000-01-01T00:00:00+00:00'")
        job=Scheduler(self.database).tick()['job_id'];_,token=self.queue.claim()
        self.assertEqual([s['source_id'] for s in self.queue.pending_sources(job)],[added.id])
        execute_job(self.queue,job,token,client=self.client,propagate_errors=True)
        self.assertEqual(self.queue.get(job)['status'],'succeeded')
        self.assertEqual(len(self.repo.list_competitions()),1)

    def test_unknown_deadline_and_uncertain_eligibility_are_held(self):
        for changes in ({'timeline':[]},{'eligibility':None},{'scope':'unknown','country':None}):
            with self.subTest(changes=changes):
                self.setup_discovery()
                self.assertEqual(self.qualify(self.observation(**changes))['status'],'held')
                # Each subcase gets an isolated DB/job.
                self.tearDown();self.setUp()

    def test_outside_indonesia_rejected(self):
        self.setup_discovery()
        self.assertEqual(self.qualify(self.observation(scope='international'))['status'],'rejected')

    def test_disabled_alias_source_is_preserved(self):
        self.setup_discovery();obs=self.observation()
        source=self.repo.create_source(SourceData(name='Disabled',kind='website',url='https://www.example.com/event?utm_source=old',adapter='public_html',enabled=False))
        result=self.qualify(obs)
        self.assertEqual(result['status'],'existing');self.assertEqual(result['source_id'],source.id)
        self.assertFalse(next(s for s in self.repo.list_sources() if s.id==source.id).enabled)

    def test_zero_new_source_limit(self):
        self.setup_discovery(max_new_sources_per_run=0)
        self.assertEqual(self.qualify(self.observation())['status'],'limited')

    def test_stricter_current_limit_applies(self):
        self.setup_discovery();obs=self.observation()
        self.update_settings(max_new_sources_per_run=0)
        self.assertEqual(self.qualify(obs)['status'],'limited')

    def test_snapshot_limit_cannot_be_raised_mid_job(self):
        self.setup_discovery(max_new_sources_per_run=0);obs=self.observation()
        self.update_settings(max_new_sources_per_run=3)
        self.assertEqual(self.qualify(obs)['status'],'limited')

    def test_source_cap_includes_disabled_and_system_sources(self):
        self.setup_discovery();obs=self.observation()
        for n in range(28):
            self.repo.create_source(SourceData(name=f'Source {n}',kind='website',url=f'https://example.org/{n}',adapter='public_html',enabled=False))
        self.assertEqual(self.qualify(obs)['status'],'limited')

    def test_quota_survives_deleted_source_and_worker_restart(self):
        self.setup_discovery(max_new_sources_per_run=1);obs=self.observation()
        result=self.qualify(obs);self.repo.delete_source(result['source_id'])
        from backend.app.job_queue import JobQueue
        self.queue=JobQueue(self.database)
        self.assertEqual(self.qualify(obs)['status'],'limited')
        with self.database.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM website_onboardings').fetchone()[0],1)

    def test_concurrent_onboarding_is_atomic(self):
        self.setup_discovery();obs=self.observation()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.qualify(obs),range(2)))
        self.assertEqual(sorted(r['status'] for r in results),['active','existing'])

    def test_distinct_candidates_share_one_job_quota(self):
        self.setup_discovery(max_new_sources_per_run=1)
        hits=[{'url':f'https://example.com/{name}','title':name} for name in ('Alpha','Beta')]
        self.client.get.side_effect=lambda url:Page(url,HTML.replace(b'Fixture',url.rsplit('/',1)[-1].encode()),'text/html')
        with patch.object(collector,'get_settings',return_value=self.config),patch.object(collector.providers,'request_json',return_value={'web':{'results':hits}}),patch.object(collector.time,'sleep'):
            execute_job(self.queue,self.job_id,self.token,client=self.client,propagate_errors=True)
        self.assertEqual(sorted(c['onboarding_status'] for c in self.candidates()),['active','limited'])
        self.assertEqual(sum(s.adapter=='discovered_article' for s in self.repo.list_sources()),1)

    def test_candidate_must_still_be_verified(self):
        self.setup_discovery();obs=self.observation()
        with self.database.transaction() as conn:
            conn.execute("UPDATE discovery_candidates SET status='failed'")
        self.assertEqual(self.qualify(obs)['status'],'held')

    def test_expired_registration_never_becomes_subscription(self):
        self.setup_discovery()
        self.client.get.side_effect=lambda url:Page(url,HTML.replace(b'2030',b'2020'),'text/html')
        self.assertEqual(self.qualify(self.observation())['status'],'rejected')

    def test_current_preferences_are_rechecked_before_activation(self):
        from backend.app.models import Preferences
        self.setup_discovery();obs=self.observation()
        self.repo.save_preferences(Preferences(categories=['hackathon'],discovery_enabled=True))
        self.assertEqual(self.qualify(obs)['status'],'rejected')

    def test_pause_and_stale_token_cannot_add_source(self):
        self.setup_discovery();obs=self.observation()
        with self.assertRaises(LostLeaseError):
            qualify(self.queue,self.job_id,'stale',self.discovery_source,*obs)
        self.update_settings(enabled=False)
        with self.assertRaises(SourceDisabledError):self.qualify(obs)
        self.assertFalse(any(s.adapter=='discovered_article' for s in self.repo.list_sources()))

    def test_missing_stored_proof_cannot_onboard(self):
        self.setup_discovery();item,saved,key=self.observation()
        self.assertEqual(self.qualify((replace(item,content_hash='not-stored'),saved,key))['status'],'held')

    def test_redirect_to_different_domain_is_held(self):
        self.setup_discovery()
        self.client.get.side_effect=lambda url:Page('https://another.example/event',HTML,'text/html')
        self.assertEqual(self.qualify(self.observation())['status'],'held')

    def test_monitor_does_not_follow_embedded_links(self):
        client=Mock();client.get.return_value=Page('https://example.com/event',HTML+b'<a href="http://127.0.0.1/">More</a>','text/html')
        result=monitor({'source_url':'https://example.com/event'},client)
        self.assertEqual(len(result.items),1);client.get.assert_called_once()
