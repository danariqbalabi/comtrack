import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock,patch

from backend.app import extraction
from backend.app.automation import AutomationStore
from backend.app.collectors.http import Page,FetchError
from backend.app.config import Settings
from backend.app.job_queue import SourceDisabledError,LostLeaseError
from backend.app.models import EvidenceData
from backend.app.quality.relevance import evaluate
from backend.app.quality.service import ingest
from backend.tests import test_discovery_automation as helpers
from backend.tests.test_public_sources import HTML
from datetime import datetime,timezone

TEXT='Intelligent Business Plan Competition 2030\nKompetisi nasional Indonesia untuk mahasiswa\nPendaftaran: 22 November 2030\nBiaya: gratis'
PAGE=Page('https://example.com/event',('<main><h2>'+TEXT.replace('\n','</h2><p>',1)+'</p></main>').encode(),'text/html')
OUTPUT=extraction.Quotes(name_quote=TEXT.splitlines()[0],facts=TEXT.splitlines()[1:])


class ExtractionTests(unittest.TestCase):
    tearDown=helpers.DiscoveryAutomationTests.tearDown

    def setUp(self):
        helpers.DiscoveryAutomationTests.setUp(self)
        helpers.DiscoveryAutomationTests.setup_discovery(self)
        self.config=Settings(_env_file=None,ai_enabled=True,ai_model='fixture:local')
        self.context=extraction.ExtractionContext(self.queue,self.job_id,self.token,self.discovery_source)
        self.context.config=self.config

    def test_grounded_quotes_become_parsed_facts_with_provenance(self):
        with patch.object(extraction,'generate',return_value=OUTPUT):item=self.context.extract(PAGE)
        self.assertEqual(item.data.category,'BPC')
        self.assertEqual(item.data.timeline[0].date.isoformat(),'2030-11-22')
        self.assertIn('mahasiswa',item.data.eligibility)
        self.assertEqual(item.field_values['_extraction']['quotes']['name_quote'],OUTPUT.name_quote)
        self.assertIn(OUTPUT.name_quote,item.raw_text)

    def test_invented_quote_is_rejected(self):
        invented=OUTPUT.model_copy(update={'facts':['Pendaftaran: 22 November 2099']})
        with patch.object(extraction,'generate',return_value=invented):self.assertIsNone(self.context.extract(PAGE))
        self.assertTrue(self.context.activity['errors'])

    def test_schema_disallows_model_supplied_amount_and_tools(self):
        for extra in ({'amount':0},{'tools':['shell']},{'url':'http://127.0.0.1/'}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                extraction.Quotes.model_validate({**OUTPUT.model_dump(),**extra})

    def test_source_without_year_stays_ambiguous(self):
        output=OUTPUT.model_copy(update={'facts':[TEXT.splitlines()[1],'Pendaftaran: 22 November']})
        page=Page(PAGE.url,PAGE.body.replace(b'November 2030',b'November'),'text/html')
        with patch.object(extraction,'generate',return_value=output):item=self.context.extract(page)
        self.assertTrue(item.data.timeline[0].needs_review)
        self.assertIsNone(item.data.timeline[0].date)

    def test_cache_is_keyed_by_content_and_model_revision(self):
        with patch.object(extraction,'generate',return_value=OUTPUT) as generate:
            self.context.extract(PAGE);self.context.extract(PAGE)
            self.assertEqual(generate.call_count,1)
            self.context.config=self.config.model_copy(update={'ai_model_revision':'2'})
            self.context.extract(PAGE);self.assertEqual(generate.call_count,2)

    def test_failed_request_is_not_repeated_after_restart(self):
        with patch.object(extraction,'generate',side_effect=ValueError('unavailable')) as generate:
            self.context.extract(PAGE)
            restarted=extraction.ExtractionContext(self.queue,self.job_id,self.token,self.discovery_source);restarted.config=self.config
            self.assertIsNone(restarted.extract(PAGE));generate.assert_called_once()

    def test_disabled_ai_never_calls_model(self):
        self.context.config=self.config.model_copy(update={'ai_enabled':False})
        with patch.object(extraction,'generate') as generate:
            self.assertIsNone(self.context.extract(PAGE));generate.assert_not_called()

    def test_good_deterministic_result_does_not_use_ai(self):
        with patch.object(extraction,'generate') as generate:
            item=self.context.extract(Page(PAGE.url,HTML,'text/html'))
            self.assertIsNotNone(item);generate.assert_not_called()

    def test_parallel_job_limit_is_persistent(self):
        self.context.config=self.config.model_copy(update={'ai_max_requests_per_job':1})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda key:self.context.reserve(key,'ai',PAGE.url),['a','b']))
        self.assertEqual(sum(results),1)

    def test_paused_job_cannot_read_cached_ai_output(self):
        with patch.object(extraction,'generate',return_value=OUTPUT):self.context.extract(PAGE)
        store=AutomationStore(self.database);state=store.get()
        store.save(state['settings'].model_copy(update={'enabled':False}),expected_version=state['version'])
        with self.assertRaises(SourceDisabledError):self.context.extract(PAGE)

    def test_stale_token_cannot_reserve_model_work(self):
        self.context.token='stale'
        with self.assertRaises(LostLeaseError):self.context.reserve('a','ai',PAGE.url)

    def test_ocr_respects_image_and_page_limits_and_stays_reviewable_after_ingest(self):
        self.context.config=self.config.model_copy(update={'ai_enabled':False,'ocr_enabled':True})
        state=AutomationStore(self.database).get()
        AutomationStore(self.database).save(state['settings'].model_copy(update={'max_images_per_post':1}),expected_version=state['version'])
        page=Page(PAGE.url,b'<main><h1>Business Plan Competition 2030</h1><img src="/one.png"><img src="/two.png"></main>','text/html')
        with patch.object(extraction.providers,'ocr_image',return_value=TEXT) as ocr:item=self.context.extract(page)
        ocr.assert_called_once()
        self.assertIsNotNone(item)
        evidence=EvidenceData(url=item.data.source_url,content_hash=item.content_hash,raw_text=item.raw_text,field_values=item.field_values,fetched_at=datetime.now(timezone.utc))
        saved,_=ingest(self.repo,item.data,evidence)
        self.assertEqual(saved.data.relevance_status,'needs_review')
        self.assertIn('[Perlu review ekstraksi]',str(saved.data.warnings))

    def test_provider_contract_is_local_fixed_and_bounded(self):
        connection=Mock();response=Mock(status=200);response.read.return_value=json.dumps({'done':True,'response':OUTPUT.model_dump_json()}).encode();connection.getresponse.return_value=response
        with patch.object(extraction.http.client,'HTTPConnection',return_value=connection) as http:
            self.assertEqual(extraction.generate(TEXT,self.config),OUTPUT)
        self.assertEqual(http.call_args.args,('127.0.0.1',11434))
        request=connection.request.call_args
        payload=json.loads(request.kwargs['body'])
        self.assertFalse(payload['stream']);self.assertEqual(payload['options']['num_predict'],2048)
        self.assertIn('untrusted',payload['system'])
        self.assertNotIn('tools',payload)

    def test_cloud_model_is_not_accepted(self):
        with self.assertRaises(ValueError):Settings(_env_file=None,ai_model='some-model:cloud')

    def test_ocr_failure_preserves_text(self):
        self.context.config=self.config.model_copy(update={'ai_enabled':False,'ocr_enabled':True})
        page=Page(PAGE.url,b'<main><h1>Business Plan Competition 2030</h1><img src="http://127.0.0.1/private"></main>','text/html')
        with patch.object(extraction.providers,'ocr_image',side_effect=FetchError('blocked')):item=self.context.extract(page)
        self.assertIsNotNone(item);self.assertTrue(self.context.activity['errors'])
