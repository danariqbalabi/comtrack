import unittest
from unittest.mock import patch, Mock
from backend.app.config import Settings
from backend.app.collectors import providers
from backend.app.collectors.http import Page
from backend.app.models import Preferences
from backend.tests import test_jobs as jobs
from backend.tests.test_public_sources import HTML


class ProviderTests(unittest.TestCase):
    setUp = jobs.QueueTests.setUp
    tearDown = jobs.QueueTests.tearDown

    def test_missing_credentials_never_make_a_provider_request(self):
        with patch.object(providers, 'get_settings', return_value=Settings(_env_file=None)), patch.object(providers, 'request_json') as request:
            for adapter in (providers.collect_discovery, providers.collect_instagram):
                with self.assertRaises(providers.ProviderUnavailable): adapter({'source_url': 'https://www.instagram.com/fixture/'})
            request.assert_not_called()

    def test_instagram_posts_use_original_urls_and_reject_wrong_owner(self):
        settings = Settings(_env_file=None, instagram_provider_enabled=True, apify_token='fixture-secret')
        posts = [{'ownerUsername': 'fixture', 'url': 'https://www.instagram.com/p/ABC/', 'caption': 'Business Plan Competition 2030\nMahasiswa Indonesia\nPendaftaran: 22 November 2030'},
                 {'ownerUsername': 'wrong', 'url': 'https://www.instagram.com/p/DEF/', 'caption': 'BCC 2030'}]
        with patch.object(providers, 'get_settings', return_value=settings), patch.object(providers, 'request_json', return_value=posts) as request:
            batch = providers.collect_instagram({'source_url': 'https://www.instagram.com/fixture/'})
        self.assertEqual(len(batch.items), 1)
        self.assertEqual(str(batch.items[0].data.source_url), posts[0]['url'])
        self.assertEqual(len(batch.errors), 1)
        self.assertNotIn('fixture-secret', batch.items[0].raw_text)
        self.assertIn('maxTotalChargeUsd=0.05', request.call_args.args[1])

    def test_discovery_verifies_details_and_keeps_candidates_separate(self):
        settings = Settings(_env_file=None, discovery_provider_enabled=True, discovery_provider='brave',brave_api_key='fixture')
        hits = {'web': {'results': [{'title': 'Business Plan', 'url': 'https://example.com/detail'}]}}
        client = Mock(); client.get.return_value = Page('https://example.com/detail', HTML, 'text/html')
        with patch.object(providers, 'get_settings', return_value=settings), patch.object(providers, 'request_json', return_value=hits), patch.object(providers, 'client_for', return_value=client), patch.object(providers.time, 'sleep'):
            batch = providers.collect_discovery({})
        self.assertEqual(len(batch.candidates), 1)
        self.assertEqual(batch.candidates[0]['status'], 'verified')
        self.assertEqual(len(batch.items), 1)
        self.assertEqual(len(self.repo.list_sources()), 1)
        self.assertEqual(self.repo.list_competitions(), [])

    def test_discovery_only_enqueued_when_preference_enabled(self):
        self.repo.save_preferences(Preferences(discovery_enabled=True))
        job_id, _ = self.queue.enqueue()
        self.assertIn('brave_discovery', [row['adapter'] for row in self.queue.pending_sources(job_id)])
        _, token = self.queue.claim()
        self.queue.finish(job_id, token, cancelled=True)
        self.repo.save_preferences(Preferences(discovery_enabled=False))
        job_id, _ = self.queue.enqueue()
        self.assertNotIn('brave_discovery', [row['adapter'] for row in self.queue.pending_sources(job_id)])

    def test_poster_ocr_is_cached_by_content_hash(self):
        settings = Settings(_env_file=None, database_path=self.database.path, ocr_enabled=True)
        client = Mock(); client.get.return_value = Page('https://example.com/poster.png', b'fixture-image-bytes', 'image/png')
        with patch.object(providers.shutil, 'which', return_value='tesseract'), patch.object(providers, 'client_for', return_value=client), patch.object(providers.subprocess, 'run', return_value=Mock(stdout=b'Fixture poster')) as run:
            self.assertEqual(providers.ocr_image('https://example.com/poster.png', settings), 'Fixture poster')
            self.assertEqual(providers.ocr_image('https://example.com/poster.png', settings), 'Fixture poster')
            run.assert_called_once()
