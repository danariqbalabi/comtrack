import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock

from backend.app import source_health
from backend.app.automation import AutomationSettings,AutomationStore
from backend.app.collectors.http import Page
from backend.app.collectors.public import parse_html,from_text
from backend.app.models import EvidenceData,Preferences
from backend.app.quality.identity import same_competition
from backend.app.quality.service import ingest
from backend.app.scheduler import Scheduler
from backend.app.source_links import attach,attach_caption
from backend.tests import test_jobs as jobs
from backend.tests.test_public_sources import HTML


class SourceHealthTests(unittest.TestCase):
    tearDown=jobs.QueueTests.tearDown

    def setUp(self):
        jobs.QueueTests.setUp(self)
        self.now=datetime.now(timezone.utc)
        self.new_job()

    def new_job(self):
        if hasattr(self,'job'):self.queue.finish(self.job,self.token,cancelled=True)
        self.job,_=self.queue.enqueue();_,self.token=self.queue.claim()
        self.job_source=self.queue.pending_sources(self.job)[0]

    def record(self,result=None,error=None,now=None):
        with self.database.transaction() as conn:
            source_health.record(conn,self.job_source,result,error,now=now or self.now)
        with self.database.connection() as conn:return dict(conn.execute('SELECT * FROM source_health').fetchone())

    def test_failures_back_off_persistently_and_completion_is_idempotent(self):
        first=self.record(error='HTTP 503')
        self.assertEqual(datetime.fromisoformat(first['next_check_at'])-self.now,timedelta(hours=12))
        self.assertEqual(self.record(error='HTTP 503')['attempts'],1)
        self.new_job();second=self.record(error='HTTP 503')
        self.assertEqual(second['consecutive_failures'],2)
        self.assertEqual(datetime.fromisoformat(second['next_check_at'])-self.now,timedelta(hours=24))

    def test_rate_limit_has_longer_minimum_delay(self):
        state=self.record(error='HTTP 429 rate limit')
        self.assertGreaterEqual(datetime.fromisoformat(state['next_check_at'])-self.now,timedelta(hours=24))

    def test_retry_delay_is_capped_at_seven_days(self):
        for _ in range(9):
            state=self.record(error='failed');self.new_job()
        self.assertEqual(datetime.fromisoformat(state['next_check_at'])-self.now,timedelta(days=7))

    def test_recovery_resets_failure_streak_and_productive_sources_keep_interval(self):
        self.record(error='failed');self.new_job()
        state=self.record({'competitions':[{'relevance_status':'relevant','outcome':'created'}]})
        self.assertEqual(state['consecutive_failures'],0);self.assertEqual(state['relevant_found'],1)
        self.assertGreater(state['score'],0)
        self.assertEqual(datetime.fromisoformat(state['next_check_at'])-self.now,timedelta(hours=6))

    def test_irrelevant_content_is_not_counted_as_productivity(self):
        state=self.record({'competitions':[{'relevance_status':'excluded','outcome':'created'}]})
        self.assertEqual(state['relevant_found'],0);self.assertEqual(state['score'],0)
        self.assertEqual(datetime.fromisoformat(state['next_check_at'])-self.now,timedelta(hours=12))

    def test_scheduler_skips_backoff_but_manual_refresh_can_recover(self):
        self.record(error='failed');self.queue.finish(self.job,self.token,cancelled=True)
        AutomationStore(self.database).save(AutomationSettings(enabled=True),expected_version=1)
        self.assertEqual(Scheduler(self.database).tick(now=self.now+timedelta(hours=1))['state'],'no_sources')
        job,_=self.queue.enqueue();self.assertIsNotNone(job)
        self.assertEqual(Scheduler(self.database).tick(now=self.now+timedelta(hours=13))['state'],'busy')

    def test_real_deadline_change_records_before_after_event_once(self):
        def observation(body):
            item=parse_html(Page('https://example.com/event',body,'text/html'))
            saved,outcome=ingest(self.repo,item.data,EvidenceData(url=item.data.source_url,content_hash=item.content_hash,raw_text=item.raw_text,field_values=item.field_values,fetched_at=self.now))
            return saved,outcome
        first,_=observation(HTML)
        second,outcome=observation(HTML.replace(b'22 November',b'25 November'))
        self.assertEqual(outcome,'updated')
        result={'competitions':[{'competition_id':second.id,'version':second.version,'outcome':outcome,'relevance_status':'relevant'}]}
        self.record(result);self.record(result)
        with self.database.connection() as conn:
            rows=conn.execute('SELECT * FROM competition_change_events').fetchall()
        self.assertEqual(len(rows),1)
        change=json.loads(rows[0]['changes_json'])['timeline']
        self.assertNotEqual(change['before'],change['after'])
        self.assertEqual(len(self.repo.list_history(first.id)),2)

    def test_duplicate_source_completion_does_not_overwrite_original(self):
        self.queue.start_source(self.job,self.token,self.job_source)
        self.queue.finish_source(self.job,self.token,self.job_source,result={'competitions':[]})
        self.queue.finish_source(self.job,self.token,self.job_source,error='duplicate failure')
        source=self.queue.get(self.job)['sources'][0]
        self.assertEqual(source['status'],'succeeded')
        with self.database.connection() as conn:self.assertEqual(conn.execute('SELECT attempts FROM source_health').fetchone()[0],1)


class SourceIdentityTests(unittest.TestCase):
    def item(self,url='https://example.com/event',target='https://forms.gle/exact-event'):
        body=HTML+b'<a href="'+target.encode()+b'">Daftar sekarang</a>'
        # Anchor must be part of article content, not navigation outside the source body.
        body=HTML.replace(b'</article>',b'<a href="'+target.encode()+b'">Daftar sekarang</a></article>')
        page=Page(url,body,'text/html')
        return attach(parse_html(page),page)

    def test_shared_explicit_registration_and_exact_identity_match_across_websites(self):
        left=self.item();right=self.item('https://campus.example/news')
        self.assertTrue(same_competition(left.data,right.data))
        self.assertIn('forms.gle/exact-event',left.raw_text)
        self.assertEqual(left.field_values['registration_url'],'https://forms.gle/exact-event')

    def test_different_editions_and_categories_are_not_merged(self):
        left=self.item().data
        self.assertFalse(same_competition(left,left.model_copy(update={'edition':'2031'})))
        self.assertFalse(same_competition(left,left.model_copy(update={'category':'BCC'})))

    def test_different_registration_urls_do_not_prove_same_competition(self):
        self.assertFalse(same_competition(self.item().data,self.item('https://other.example/event','https://forms.gle/other-event').data))

    def test_private_registration_url_is_not_retained(self):
        self.assertIsNone(self.item(target='http://127.0.0.1/secret').data.registration_url)

    def test_explicit_caption_registration_link_is_provenance(self):
        item=from_text('Business Plan Competition 2030','Mahasiswa Indonesia\nPendaftaran: 22 November 2030\nDaftar: https://forms.gle/event-2030','https://instagram.com/p/ABC/')
        self.assertEqual(str(attach_caption(item).data.registration_url),'https://forms.gle/event-2030')
