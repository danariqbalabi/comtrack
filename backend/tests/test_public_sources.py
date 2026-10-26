import json
import unittest
from unittest.mock import Mock
from backend.app.collectors.http import Page, FetchError
from backend.app.collectors.public import collect_html, collect_rss, from_text, parse_html

HTML = b'<main><h1>Fixture Business Plan Competition 2030</h1><article>Kompetisi nasional Indonesia untuk mahasiswa<p>Pendaftaran: 22 November 2030</p><p>Biaya: Rp50.000 per tim</p></article></main>'


class PublicSourcesTests(unittest.TestCase):
    def source(self, **config):
        return {'source_url': 'https://example.com/', 'config_json': json.dumps(config)}

    def test_explicit_deadline_provenance_and_unknown_amounts(self):
        item = parse_html(Page('https://example.com/event', HTML, 'text/html'))
        self.assertEqual(item.data.category, 'BPC')
        self.assertEqual(str(item.data.timeline[0].date), '2030-11-22')
        self.assertIsNone(item.data.fees[0].amount)
        self.assertIn('Rp50.000', item.raw_text)
        self.assertEqual(item.data.edition, '2030')

    def test_list_fetches_details_and_retains_failure(self):
        client = Mock()
        client.get.side_effect = [Page('https://example.com/', b'<a class="item" href="/a">One</a><a class="item" href="/b">Two</a>', 'text/html'), Page('https://example.com/a', HTML, 'text/html'), FetchError('HTTP 403')]
        batch = collect_html(self.source(links_selector='.item'), client)
        self.assertEqual(len(batch.items), 1)
        self.assertEqual(batch.inspected, 2)
        self.assertEqual(len(batch.errors), 1)

    def test_rss_verifies_article_instead_of_ingesting_snippet(self):
        client = Mock()
        rss = b'<rss><channel><item><title>Business Plan Competition</title><link>https://example.com/article</link><description>Snippet only</description></item></channel></rss>'
        client.get.side_effect = [Page('https://example.com/', rss, 'application/rss+xml'), Page('https://example.com/article', HTML, 'text/html')]
        batch = collect_rss(self.source(), client)
        self.assertEqual(len(batch.items), 1)
        self.assertIn('22 November', batch.items[0].raw_text)
        self.assertNotIn('Snippet only', batch.items[0].raw_text)

    def test_unsafe_xml_and_changed_selectors_fail_honestly(self):
        client = Mock()
        client.get.return_value = Page('https://example.com/', b'<!DOCTYPE foo [<!ENTITY x "oops">]><rss/>', 'text/xml')
        with self.assertRaises(ValueError): collect_rss(self.source(), client)
        client.get.return_value = Page('https://example.com/', HTML, 'text/html')
        with self.assertRaises(ValueError): collect_html(self.source(links_selector='.missing'), client)

    def test_unrelated_article_skipped_and_ambiguous_categories_reviewed(self):
        self.assertIsNone(from_text('Lomba puisi', 'Untuk mahasiswa Indonesia', 'https://example.com/a'))
        item = from_text('Festival BPC dan BCC', 'Kompetisi Indonesia', 'https://example.com/a')
        self.assertEqual(item.data.category, 'uncertain')

    def test_international_title_not_misclassified_as_indonesia(self):
        item = from_text('International Business Plan Competition 2030', 'Open to mahasiswa Indonesia', 'https://example.com/a')
        self.assertEqual(item.data.scope, 'international')

    def test_navigation_and_fee_mentions_are_not_undated_registration_phases(self):
        item = from_text('Business Plan Competition 2030', 'Pendaftaran belum dibuka\nHadiah menarik\nInfo lain\nPendaftaran Dibuka\n3 Agustus 2030\nPendaftaran Ditutup\n14 September 2030\nGrand Final\n25 September 2030\nBiaya pendaftaran\nRp50.000\nInformasi lain', 'https://example.com/a')
        registrations = [entry for entry in item.data.timeline if entry.kind == 'registration']
        self.assertEqual(len(registrations), 1)
        self.assertEqual(str(registrations[0].date), '2030-09-14')
