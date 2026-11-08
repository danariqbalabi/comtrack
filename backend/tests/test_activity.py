import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from backend.app.activity_api import router
from backend.app.models import CompetitionData,TimelineEntry
from backend.app.worker import execute_job
from backend.tests import test_jobs as jobs


class ActivityTests(unittest.TestCase):
    setUp=jobs.QueueTests.setUp
    tearDown=jobs.QueueTests.tearDown
    request=jobs.ApiTests.request
    routers=(router,)
    protect=True

    def test_read_endpoints_do_not_search_or_mutate(self):
        with self.database.connection() as conn:
            before=conn.total_changes
        with patch('backend.app.collectors.providers.request_json',side_effect=AssertionError('provider')),patch('backend.app.collectors.http.PublicClient.get',side_effect=AssertionError('web')):
            for path in ('activity','sources','runs','changes','deadlines'):
                status,body=self.request('GET','/api/automation/'+path)
                self.assertEqual(status,200,(path,body))
        self.assertIsNone(self.queue.latest())
        self.assertEqual(self.repo.list_competitions(),[])

    def test_empty_activity_is_honest(self):
        status,body=self.request('GET','/api/automation/activity')
        self.assertEqual(status,200);self.assertIsNone(body['last_job'])
        self.assertEqual(body['budget']['requests_reserved'],0)
        self.assertEqual(body['source_statuses'],{'not_checked':1})

    def test_completed_job_counts_and_source_health_are_visible(self):
        job,_=self.queue.enqueue();_,token=self.queue.claim()
        execute_job(self.queue,job,token,adapters={self.source.adapter:self.adapter})
        status,body=self.request('GET','/api/automation/activity')
        self.assertEqual(body['last_job']['counts']['created'],1)
        status,body=self.request('GET','/api/automation/sources')
        self.assertEqual(body['items'][0]['attempts'],1)
        self.assertTrue(body['items'][0]['next_check_at'])
        status,body=self.request('GET','/api/automation/runs')
        self.assertEqual(body['items'][0]['trigger'],'manual')
        self.assertEqual(body['items'][0]['sources'][0]['status'],'succeeded')
        self.assertNotIn('worker_token',json.dumps(body))
        self.assertNotIn('config_json',json.dumps(body))

    def test_failure_reason_is_visible(self):
        job,_=self.queue.enqueue();_,token=self.queue.claim()
        from unittest.mock import Mock
        execute_job(self.queue,job,token,adapters={self.source.adapter:Mock(side_effect=ValueError('Fixture struktur berubah'))})
        body=self.request('GET','/api/automation/runs')[1]
        self.assertIn('struktur berubah',body['items'][0]['sources'][0]['error'])
        self.assertEqual(body['items'][0]['sources_failed'],1)

    def competition(self,days,**changes):
        date=(datetime.now(timezone.utc)+timedelta(days=days)).date()
        data=CompetitionData(name=f'Business Plan Competition {date.year}',category='BPC',edition=str(date.year),scope='indonesia',content_kind='competition',eligibility='Mahasiswa Indonesia',
            source_url='https://example.com/'+str(days),timeline=[TimelineEntry(kind='registration',raw_text='Pendaftaran '+date.isoformat(),date=date,needs_review=False)])
        return self.repo.create_competition(data.model_copy(update=changes))

    def test_deadlines_include_near_verified_dates_only(self):
        near=self.competition(2);self.competition(10);self.competition(-2)
        self.competition(3,scope='international')
        self.competition(1,timeline=[TimelineEntry(kind='registration',raw_text='22 November',needs_review=True)])
        status,body=self.request('GET','/api/automation/deadlines')
        self.assertEqual(status,200);self.assertEqual([item['competition_id'] for item in body['items']],[near.id])

    def test_change_events_are_paginated_without_losing_before_after(self):
        competition=self.competition(2)
        with self.database.transaction() as conn:
            conn.execute('INSERT INTO competition_change_events(competition_id,version,changes_json,created_at) VALUES (?,2,?,?)',
                (competition.id,json.dumps({'fees':{'before':[],'after':[{'raw_text':'gratis'}]}}),datetime.now(timezone.utc).isoformat()))
        status,body=self.request('GET','/api/automation/changes?limit=1')
        self.assertEqual(status,200);self.assertEqual(body['items'][0]['changes']['fees']['before'],[])
        self.assertEqual(self.request('GET','/api/automation/changes?offset=1')[1]['items'],[])

    def test_precise_timestamp_without_separate_date_is_still_a_deadline(self):
        at=datetime.now(timezone.utc)+timedelta(days=2)
        record=self.competition(2,timeline=[TimelineEntry(kind='registration',raw_text='Pendaftaran '+at.isoformat(),at=at,needs_review=False)])
        body=self.request('GET','/api/automation/deadlines')[1]
        self.assertEqual(body['items'][0]['competition_id'],record.id)

    def test_endpoints_validate_bounds(self):
        for path in ('runs?offset=-1','runs?limit=31','changes?limit=101','deadlines?days=31','deadlines?limit=101'):
            with self.subTest(path=path):self.assertEqual(self.request('GET','/api/automation/'+path)[0],422)

    def test_provider_breakdown_counts_shared_reservations(self):
        job,_=self.queue.enqueue();source=self.queue.pending_sources(job)[0]
        day=datetime.now(timezone.utc).date().isoformat()
        with self.database.transaction() as conn:
            conn.execute("INSERT INTO paid_provider_requests(job_source_id,action_key,provider,day_utc,reserved_microusd,status,created_at) VALUES (?,'profile:fixture','apify',?,50000,'failed',?)",(source['id'],day,datetime.now(timezone.utc).isoformat()))
        body=self.request('GET','/api/automation/activity')[1]
        self.assertEqual(body['budget']['requests_reserved'],1)
        self.assertEqual(body['budget']['estimated_usd_reserved'],'0.05')
        self.assertEqual(body['budget']['by_provider'][0]['provider'],'apify')
