import hashlib
import ipaddress
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.collect import CollectionBusyError, run_collection
from backend.app.collectors.http import FetchError, Page, PublicClient, is_public, public_url
from backend.app.collectors.ou_festival import ALLOWED_HOSTS, SOURCE_URL, ExtractionError, extract
from backend.app.quality.dates import parse_timeline
from backend.app.database import Database
from backend.app.repository import Repository

FIXTURE = Path(__file__).with_name("fixtures") / "ou_festival.html"


def fixture_page(html=None):
    return Page(SOURCE_URL, html if html is not None else FIXTURE.read_bytes(), "text/html; charset=utf-8")


class ExtractionTests(unittest.TestCase):
    def test_epic_deadline_is_not_festival_or_other_branch_deadline(self):
        result = extract(fixture_page())
        self.assertEqual(str(result.data.timeline[0].date), "2030-11-22")
        self.assertEqual(result.data.category, "BPC")
        self.assertIn("2030/2031", result.data.edition)
        self.assertEqual(result.data.team_min, 2)
        self.assertEqual(result.data.team_max, 3)
        self.assertIsNone(result.data.country)
        self.assertIsNone(result.data.location)

    def test_registration_submission_and_university_final_remain_distinct(self):
        event = extract(fixture_page()).data
        self.assertEqual([entry.kind for entry in event.timeline], ["registration", "submission", "submission", "final"])
        self.assertEqual(str(event.timeline[-1].date), "2031-01-17")
        self.assertIn("mahasiswa", event.timeline[-1].label)
        self.assertTrue(all(entry.at is None for entry in event.timeline))
        self.assertTrue(all(entry.timezone == "WIB" for entry in event.timeline))

    def test_stage_specific_fees_not_reported_as_unconditionally_free(self):
        result = extract(fixture_page())
        self.assertEqual([str(fee.amount) for fee in result.data.fees], ["0", "60000", "75000"])
        self.assertTrue(all(fee.basis == "unknown" for fee in result.data.fees))
        self.assertIn("Jika lolos", result.data.fees[0].raw_text)
        self.assertEqual(result.field_values["fees"], result.data.fees[1].raw_text)

    def test_snapshot_contains_evidence_but_not_scripts_or_other_branches(self):
        result = extract(fixture_page())
        self.assertNotIn("attacker", result.raw_text)
        self.assertNotIn("31 Desember", result.field_values["timeline.0"])
        self.assertEqual(result.content_hash, hashlib.sha256(result.raw_text.encode()).hexdigest())
        self.assertIn("22 November", result.field_values["timeline.0"])
        self.assertEqual(str(result.data.registration_url), "https://ou-festival.com/competition/53")
        self.assertEqual(str(result.data.guidebook_url), "https://bit.ly/fixtureEPIC")

    def test_schema_change_fails_instead_of_fake_success(self):
        for old, new in [(b'id="berkas-epic"', b'id="changed"'), (b"<h3>EPIC</h3>", b"<h3>NEW</h3>"), (b"<dt>Biaya</dt>", b"<dt>Changed</dt>")]:
            with self.subTest(field=old):
                with self.assertRaises(ExtractionError):
                    extract(fixture_page(FIXTURE.read_bytes().replace(old, new)))

    def test_missing_year_or_invalid_date_not_guessed(self):
        for raw in ("12 November", "31 Februari 2030", "01/02/2030", "22 November 2030 atau 5 Desember 2030"):
            self.assertIsNone(parse_timeline(raw).date, raw)
        changed = FIXTURE.read_bytes().replace(b"22 November 2030", b"22 November")
        event = extract(fixture_page(changed)).data
        self.assertIsNone(event.timeline[0].date)
        self.assertTrue(event.timeline[0].needs_review)
        self.assertEqual(event.registration_status, "unknown")

    def test_unrelated_countdown_or_navigation_changes_do_not_create_new_snapshot(self):
        original = FIXTURE.read_bytes()
        changed = original.replace(b"</body>", b"<nav>Countdown changed 999</nav></body>")
        self.assertEqual(extract(fixture_page(original)).content_hash, extract(fixture_page(changed)).content_hash)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "radar.db")
        self.database.migrate()
        self.repository = Repository(self.database)
        self.client = Mock(spec=PublicClient)
        self.client.get.return_value = fixture_page()

    def tearDown(self):
        self.temp.cleanup()

    def test_manual_collection_and_repeat_are_persistent_and_idempotent(self):
        first = run_collection(self.repository, self.client)
        second = run_collection(Repository(Database(self.database.path)), self.client)
        self.assertEqual(first["outcome"], "created")
        self.assertEqual(second["outcome"], "unchanged")
        self.assertEqual(first["competition_id"], second["competition_id"])
        self.assertEqual(second["evidence_count"], 1)
        self.assertEqual(len(self.repository.list_history(first["competition_id"])), 1)
        self.assertEqual(self.repository.get_job(second["job_id"])["status"], "succeeded")
        self.assertEqual(self.repository.list_sources()[0].status, "ok")

    def test_deadline_change_updates_one_record_and_keeps_both_snapshots(self):
        first = run_collection(self.repository, self.client)
        self.client.get.return_value = fixture_page(FIXTURE.read_bytes().replace(b"22 November 2030", b"25 November 2030"))
        second = run_collection(self.repository, self.client)
        self.assertEqual(second["outcome"], "updated")
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["evidence_count"], 2)
        self.assertEqual(second["competition_id"], first["competition_id"])
        self.assertEqual(self.repository.list_history(first["competition_id"])[0]["data"]["timeline"][0]["date"], "2030-11-22")

    def test_network_failure_is_logged_without_erasing_previous_results(self):
        saved = run_collection(self.repository, self.client)
        previous = self.repository.get_competition(saved["competition_id"])
        success_at = self.repository.list_sources()[0].last_success_at
        self.client.get.side_effect = FetchError("HTTP 403 dari sumber.", status=403)
        with self.assertRaises(FetchError): run_collection(self.repository, self.client)
        self.assertEqual(self.repository.get_competition(previous.id), previous)
        source = self.repository.list_sources()[0]
        self.assertEqual(source.status, "failed")
        self.assertEqual(source.last_success_at, success_at)
        self.assertEqual(self.repository.get_job(2)["status"], "failed")
        self.assertTrue(any("403" in log["message"] for log in self.repository.list_logs(2)))

    def test_changed_schema_preserves_existing_data_and_records_failure(self):
        first = run_collection(self.repository, self.client)
        self.client.get.return_value = fixture_page(b"<html>Login required</html>")
        with self.assertRaises(ExtractionError): run_collection(self.repository, self.client)
        self.assertEqual(self.repository.get_competition(first["competition_id"]).version, 1)
        self.assertEqual(self.repository.get_job(2)["status"], "failed")

    def test_disabled_source_is_preserved_and_not_fetched(self):
        run_collection(self.repository, self.client)
        self.repository.set_source_enabled(1, False)
        self.client.reset_mock()
        with self.assertRaises(ValueError): run_collection(self.repository, self.client)
        self.client.get.assert_not_called()
        self.assertFalse(self.repository.list_sources()[0].enabled)

    def test_overlapping_run_does_not_fetch(self):
        self.repository.create_job()
        with self.assertRaises(CollectionBusyError): run_collection(self.repository, self.client)
        self.client.get.assert_not_called()

    def test_interruption_finishes_job_as_cancelled(self):
        self.client.get.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): run_collection(self.repository, self.client)
        self.assertEqual(self.repository.get_job(1)["status"], "cancelled")


class PublicHttpTests(unittest.TestCase):
    def test_unsafe_schemes_ports_credentials_hosts_and_ips_are_blocked(self):
        urls = ["file:///etc/passwd", "https://u:p@ou-festival.com/", "https://ou-festival.com:8000/", "http://localhost/", "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/", "https://attacker.example/"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(FetchError):
                public_url(url, ALLOWED_HOSTS | frozenset({"localhost", "127.0.0.1", "::1", "169.254.169.254"}))
        self.assertFalse(is_public(ipaddress.ip_address("::ffff:127.0.0.1")))

    def test_private_dns_is_rejected_before_connection(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch("backend.app.collectors.http.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]), patch("backend.app.collectors.http.socket.create_connection") as connect:
            with self.assertRaises(FetchError): client._request(SOURCE_URL, time.monotonic() + 10)
            connect.assert_not_called()

    def test_connection_is_pinned_to_validated_address_with_hostname_tls(self):
        client = PublicClient(ALLOWED_HOSTS)
        response = Mock(status=200)
        response.getheaders.return_value = [("Content-Type", "text/html")]
        response.read.side_effect = [b"<p>source</p>", b""]
        connection = Mock(); connection.getresponse.return_value = response
        tls = Mock(); tls.wrap_socket.return_value = Mock()
        with patch("backend.app.collectors.http.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), patch("backend.app.collectors.http.socket.create_connection") as connect, patch("backend.app.collectors.http.http.client.HTTPConnection", return_value=connection), patch("backend.app.collectors.http.ssl.create_default_context", return_value=tls):
            page, _, _ = client._request(SOURCE_URL, time.monotonic() + 10)
        self.assertEqual(connect.call_args.args[0], ("8.8.8.8", 443))
        self.assertEqual(tls.wrap_socket.call_args.kwargs["server_hostname"], "ou-festival.com")
        self.assertEqual(page.body, b"<p>source</p>")

    def test_robots_denial_prevents_page_request(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch.object(client, "_request", return_value=(Page(SOURCE_URL+"robots.txt", b"User-agent: *\nDisallow: /\n", "text/plain"), 200, {})) as request:
            with self.assertRaises(FetchError): client.get(SOURCE_URL)
            self.assertEqual(request.call_count, 1)

    def test_oversized_response_is_rejected_before_reading_body(self):
        client = PublicClient(ALLOWED_HOSTS, max_bytes=32)
        response = Mock(status=200)
        response.getheaders.return_value = [("Content-Type", "text/html"), ("Content-Length", "1000")]
        connection = Mock(); connection.getresponse.return_value = response
        with patch("backend.app.collectors.http.socket.getaddrinfo", return_value=[(2,1,6,"",("8.8.8.8",443))]), patch("backend.app.collectors.http.socket.create_connection"), patch("backend.app.collectors.http.http.client.HTTPConnection", return_value=connection), patch("backend.app.collectors.http.ssl.create_default_context"):
            with self.assertRaises(FetchError): client._request(SOURCE_URL, time.monotonic()+10)
        response.read.assert_not_called()
        connection.close.assert_called_once()

    def test_missing_robots_file_is_distinct_from_access_denied(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch.object(client, "_request", side_effect=[(Page(SOURCE_URL+"robots.txt",b"",""),404,{}),(Page(SOURCE_URL,b"ok","text/html"),200,{})]):
            self.assertEqual(client.get(SOURCE_URL).body, b"ok")

    def test_robots_failure_is_not_treated_as_permission(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch.object(client, "_request", return_value=(Page(SOURCE_URL+"robots.txt", b"", "text/plain"), 403, {})) as request:
            with self.assertRaises(FetchError): client.get(SOURCE_URL)
            self.assertEqual(request.call_count, 1)

    def test_redirect_to_internal_address_is_blocked(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch.object(client, "_request", return_value=(Page(SOURCE_URL,b"",""),302,{"location":"http://127.0.0.1/secret"})) as request:
            with self.assertRaises(FetchError): client._get(SOURCE_URL, check_robots=False, deadline=time.monotonic()+10)
            self.assertEqual(request.call_count, 1)

    def test_rate_limit_retry_after_is_respected(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch.object(client, "_request", return_value=(Page(SOURCE_URL,b"",""),429,{"retry-after":"60"})) as request, patch("backend.app.collectors.http.time.sleep") as sleep:
            with self.assertRaises(FetchError): client._get(SOURCE_URL, check_robots=False, deadline=time.monotonic()+10)
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()

    def test_transient_server_error_has_one_retry(self):
        client = PublicClient(ALLOWED_HOSTS)
        with patch.object(client, "_request", side_effect=[(Page(SOURCE_URL,b"",""),503,{}),(Page(SOURCE_URL,b"ok","text/plain"),200,{})]) as request, patch("backend.app.collectors.http.time.sleep"):
            page = client._get(SOURCE_URL, check_robots=False, deadline=time.monotonic()+10)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(page.body, b"ok")


if __name__ == "__main__":
    unittest.main()
