import unittest
from backend.app.feed_api import router as feed_router
from backend.app.settings_api import router as settings_router
from backend.app.jobs_api import router as jobs_router
from backend.tests import test_jobs as jobs


class ProductTests(unittest.TestCase):
    setUp = jobs.QueueTests.setUp
    tearDown = jobs.QueueTests.tearDown
    run_job = jobs.QueueTests.run_job
    request = jobs.ApiTests.request
    routers = (feed_router, settings_router, jobs_router)
    protect = True
    headers = {"x-lomba-radar": "1"}

    def test_feed_contains_real_ingested_observation_and_search_filters(self):
        self.queue.enqueue(); self.run_job()
        self.assertEqual(self.request('GET', '/api/competitions')[1]['total'], 1)
        self.assertEqual(self.request('GET', '/api/competitions?category=BCC')[1]['total'], 0)
        self.assertEqual(self.request('GET', '/api/competitions?q=epic')[1]['total'], 1)
        self.assertEqual(self.request('GET', '/api/competitions?q=absent')[1]['total'], 0)
        self.assertEqual(self.request('GET', '/api/competitions?offset=-1')[0], 422)
        status, detail = self.request('GET', '/api/competitions/1')
        self.assertEqual(status, 200)
        self.assertEqual(len(detail['evidence']), 1)
        self.assertEqual(len(detail['history']), 1)
        self.assertEqual(self.request('GET', '/api/competitions/999')[0], 404)

    def test_settings_mutations_require_same_origin_header(self):
        source = {'name': 'Fixture', 'kind': 'instagram', 'url': '@csrelatedcompetition'}
        self.assertEqual(self.request('POST', '/api/sources', source)[0], 403)
        self.assertEqual(self.request('POST', '/api/sources', source, {**self.headers, 'origin': 'https://evil.example'})[0], 403)
        status, saved = self.request('POST', '/api/sources', source, self.headers)
        self.assertEqual(status, 201)
        self.assertEqual(saved['url'], 'https://www.instagram.com/csrelatedcompetition/')
        self.assertEqual(self.request('POST', '/api/sources', source, self.headers)[0], 409)
        self.assertEqual(self.request('PATCH', f"/api/sources/{saved['id']}", {'enabled': False}, self.headers)[0], 200)
        self.assertFalse(self.repo.list_sources()[-1].enabled)
        self.assertEqual(self.request('DELETE', f"/api/sources/{saved['id']}", headers=self.headers)[0], 200)

    def test_sources_reject_private_urls_and_instagram_post_urls(self):
        for url in ('http://127.0.0.1/', 'http://10.1.1.1/', 'http://localhost/', 'file:///secret', 'https://user:secret@example.com/', 'https://example.com:9000/'):
            with self.subTest(url=url):
                self.assertEqual(self.request('POST', '/api/sources', {'name': 'Bad', 'url': url}, self.headers)[0], 422)
        self.assertEqual(self.request('POST', '/api/sources', {'name': 'Bad', 'kind': 'instagram', 'url': 'https://www.instagram.com/p/postid/'}, self.headers)[0], 422)

    def test_preferences_persist_and_recalculate_visibility_without_fetch(self):
        self.queue.enqueue(); self.run_job()
        prefs = self.request('GET', '/api/preferences')[1]
        prefs['categories'] = ['hackathon']
        self.assertEqual(self.request('PUT', '/api/preferences', prefs, self.headers)[0], 200)
        self.assertEqual(self.request('GET', '/api/competitions')[1]['total'], 0)
        self.assertEqual(len(self.repo.list_competitions()), 1)
        prefs['country'] = 'US'
        self.assertEqual(self.request('PUT', '/api/preferences', prefs, self.headers)[0], 422)
