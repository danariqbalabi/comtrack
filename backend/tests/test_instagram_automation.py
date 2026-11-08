import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from backend.app import instagram,extraction
from backend.app.automation import AutomationStore
from backend.app.collectors import providers
from backend.app.collectors.http import FetchError,Page
from backend.app.config import Settings
from backend.app.discovery import DiscoveryBlocked
from backend.app.extraction import ExtractionContext
from backend.app.instagram_api import router
from backend.app.models import SourceData
from backend.app.provider_budget import daily_usage
from backend.app.scheduler import Scheduler
from backend.app.worker import execute_job
from backend.tests import test_discovery_automation as helpers

PROFILE={'username':'lombafixture','private':False,'biography':'Media informasi lomba dan kompetisi untuk mahasiswa Indonesia','email':'discard@example.com'}
POST={'url':'https://www.instagram.com/p/ABC123/','ownerUsername':'lombafixture',
      'caption':'Business Plan Competition 2030\nKompetisi nasional Indonesia untuk mahasiswa\nPendaftaran: 22 November 2030',
      'displayUrl':'https://example.com/one.jpg','childPosts':[{'displayUrl':'https://example.com/two.jpg'}]}


class InstagramTests(unittest.TestCase):
    tearDown=helpers.DiscoveryAutomationTests.tearDown
    request=helpers.DiscoveryAutomationTests.request
    routers=(router,)
    protect=True

    def setUp(self):
        helpers.DiscoveryAutomationTests.setUp(self)
        helpers.DiscoveryAutomationTests.setup_discovery(self)
        self.config=Settings(_env_file=None,instagram_provider_enabled=True,apify_token='fixture-secret',apify_max_charge_usd=0.01)
        self.context=ExtractionContext(self.queue,self.job_id,self.token,self.discovery_source);self.context.config=self.config

    def test_public_profile_requires_explicit_competition_identity(self):
        cases=[({'private':True},'rejected'),({'private':None},'held'),({'private':'false'},'held'),
               ({'private':False,'biography':'Personal diary, love lomba'},'rejected'),
               ({'private':False,'biography':'Mahasiswa dan penikmat kopi'},'held'),
               ({'private':False,'biography':'Official penyelenggara Business Plan Competition Indonesia'},'approved')]
        for fields,expected in cases:
            with self.subTest(fields=fields):self.assertEqual(instagram.classify({**PROFILE,**fields},'lombafixture')[0],expected)
        self.assertEqual(instagram.classify({**PROFILE,'username':'other'},'lombafixture')[0],'held')
        self.assertEqual(instagram.classify({'username':'lombafixture','biography':PROFILE['biography']},'lombafixture')[0],'held')

    def test_profile_url_normalization_rejects_posts_and_fake_hosts(self):
        self.assertEqual(instagram.profile_url('https://instagram.com/LOMBAfixture/?utm_source=x')[0],'lombafixture')
        for url in ('https://instagram.com/p/ABC/','https://instagram.com/explore/','https://instagram.com.evil.test/account/','http://127.0.0.1/account/'):
            with self.subTest(url=url),self.assertRaises((ValueError,FetchError)):instagram.profile_url(url)

    def test_discovered_account_is_added_once_and_no_private_fields_are_retained(self):
        with patch.object(providers,'request_json',return_value=[PROFILE]) as request:
            first=instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/competition')
            second=instagram.consider(self.context,'https://www.instagram.com/lombafixture/','https://example.com/other')
        self.assertEqual(first[0],'active');self.assertEqual(second[0],'existing');request.assert_called_once()
        with self.database.connection() as conn:
            candidate=dict(conn.execute('SELECT * FROM instagram_candidates').fetchone())
            ledger=conn.execute('SELECT result_json FROM paid_provider_requests').fetchone()[0]
        self.assertNotIn('discard@example.com',ledger)
        self.assertEqual(candidate['discovered_from'],'https://example.com/competition')
        self.assertEqual(sum(s.kind=='instagram' for s in self.repo.list_sources()),1)

    def test_no_credential_means_no_provider_call(self):
        self.context.config=Settings(_env_file=None)
        with patch.object(providers,'request_json') as request:
            result=instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/')
            request.assert_not_called();self.assertEqual(result[0],'held')

    def test_zero_new_source_quota_does_not_buy_profile_validation(self):
        self.context.snapshot=self.context.snapshot.model_copy(update={'max_new_sources_per_run':0})
        with patch.object(providers,'request_json') as request:
            self.assertEqual(instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/')[0],'limited')
            request.assert_not_called()

    def test_existing_disabled_account_is_not_reenabled(self):
        source=self.repo.create_source(SourceData(name='IG',kind='instagram',url='https://instagram.com/lombafixture/',adapter='instagram_provider',enabled=False))
        with patch.object(providers,'request_json',return_value=[PROFILE]):
            self.assertEqual(instagram.consider(self.context,str(source.url),'https://example.com/')[0],'existing')
        self.assertFalse(next(s for s in self.repo.list_sources() if s.id==source.id).enabled)

    def test_private_profile_is_rejected_without_subscription(self):
        with patch.object(providers,'request_json',return_value=[{**PROFILE,'private':True}]):
            self.assertEqual(instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/')[0],'rejected')
        self.assertFalse(any(s.kind=='instagram' for s in self.repo.list_sources()))

    def prepare_account_job(self):
        self.queue.finish(self.job_id,self.token,cancelled=True)
        self.repo.set_source_enabled(self.discovery_source['source_id'],False)
        account=self.repo.create_source(SourceData(name='IG',kind='instagram',url='https://www.instagram.com/lombafixture/',adapter='instagram_provider'))
        with self.database.transaction() as conn:conn.execute("UPDATE automation_schedule SET next_run_at='2000-01-01T00:00:00+00:00'")
        self.job_id=Scheduler(self.database).tick()['job_id'];_,self.token=self.queue.claim()
        self.account_source=next(s for s in self.queue.pending_sources(self.job_id) if s['source_id']==account.id)

    def test_worker_rechecks_public_profile_before_post_ingestion(self):
        self.prepare_account_job()
        with patch.object(extraction,'get_settings',return_value=self.config),patch.object(providers,'request_json',side_effect=[[PROFILE],[POST]]) as request:
            execute_job(self.queue,self.job_id,self.token,propagate_errors=True)
        self.assertEqual(request.call_count,2)
        self.assertIn('instagram-profile-scraper',request.call_args_list[0].args[1])
        self.assertIn('maxTotalChargeUsd=0.01',request.call_args_list[1].args[1])
        self.assertEqual(len(self.repo.list_competitions()),1)
        self.assertEqual(str(self.repo.list_competitions()[0].data.source_url),POST['url'])

    def test_private_profile_never_requests_posts(self):
        self.prepare_account_job()
        with patch.object(extraction,'get_settings',return_value=self.config),patch.object(providers,'request_json',return_value=[{**PROFILE,'private':True}]) as request:
            execute_job(self.queue,self.job_id,self.token)
        request.assert_called_once();self.assertEqual(self.repo.list_competitions(),[])

    def test_wrong_post_owner_is_rejected(self):
        self.prepare_account_job()
        with patch.object(extraction,'get_settings',return_value=self.config),patch.object(providers,'request_json',side_effect=[[PROFILE],[{**POST,'ownerUsername':'personal'}]]):
            result=instagram.collect(self.queue,self.job_id,self.token,self.account_source)
        self.assertEqual(result.items,[]);self.assertTrue(result.errors)

    def test_brave_and_instagram_share_daily_request_quota(self):
        state=AutomationStore(self.database).get()
        AutomationStore(self.database).save(state['settings'].model_copy(update={'provider_daily_request_limit':1}),expected_version=state['version'])
        self.context.snapshot=self.context.snapshot.model_copy(update={'provider_daily_request_limit':1})
        self.context.config=self.config
        with patch.object(providers,'request_json',return_value=[PROFILE]):
            instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/')
        with self.assertRaises(DiscoveryBlocked):self.context_snapshot_reserve_brave()
        with self.database.connection() as conn:
            self.assertEqual(daily_usage(conn,datetime.now(timezone.utc).date().isoformat())[0],1)

    def context_snapshot_reserve_brave(self):
        self.context_for_brave=helpers.DiscoveryContext(self.queue,self.job_id,self.token,self.discovery_source)
        return self.context_for_brave.reserve(0,self.context_for_brave.queries[0],helpers.Decimal('0.001'))

    def test_failed_profile_call_does_not_repeat_within_job(self):
        with patch.object(providers,'request_json',side_effect=ValueError('provider failed')) as request:
            for _ in range(2):instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/')
            request.assert_called_once()

    def test_discovered_links_are_bounded_and_keep_parent_url(self):
        page=Page('https://example.com/',b'<main>'+b''.join(f'<a href="https://instagram.com/media{i}/">IG</a>'.encode() for i in range(10))+b'</main>','text/html')
        with patch.object(instagram,'consider') as consider:
            instagram.discover_links(self.context,page)
        self.assertEqual(consider.call_count,3)
        self.assertTrue(all(call.args[2]==page.url for call in consider.call_args_list))

    def test_candidates_api_never_exposes_cached_profile_or_token(self):
        with patch.object(providers,'request_json',return_value=[PROFILE]):instagram.consider(self.context,'https://instagram.com/lombafixture/','https://example.com/')
        status,body=self.request('GET','/api/instagram/candidates')
        self.assertEqual(status,200);self.assertEqual(body['total'],1)
        self.assertNotIn('profile_json',json.dumps(body));self.assertNotIn('fixture-secret',json.dumps(body))
        self.assertEqual(self.request('GET','/api/instagram/candidates?limit=101')[0],422)
