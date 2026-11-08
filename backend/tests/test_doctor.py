import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.app.config import Settings
from backend.app.database import Database
from scripts import doctor


class DoctorTests(unittest.TestCase):
    def test_missing_database_is_reported_without_creating_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing.db'
            with patch.object(doctor,'get_settings',return_value=Settings(_env_file=None,database_path=path)):
                report=doctor.inspect()
            self.assertFalse(report['database']['exists']);self.assertFalse(path.exists())
            self.assertEqual(report['network_requests'],0)

    def test_readiness_report_does_not_leak_credentials_or_activate_automation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'radar.db';Database(path).migrate()
            config=Settings(_env_file=None,database_path=path,discovery_provider='brave',brave_api_key='fixture-private-brave',apify_token='fixture-private-apify',access_password='fixture-private-password')
            with patch.object(doctor,'get_settings',return_value=config):report=doctor.inspect()
            self.assertFalse(report['automation']['enabled'])
            self.assertFalse(report['automation']['paid_allowed'])
            self.assertEqual(report['database']['integrity'],'ok')
            self.assertNotIn('fixture-private',json.dumps(report))

    def test_corrupt_database_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'broken.db';path.write_bytes(b'not sqlite')
            with patch.object(doctor,'get_settings',return_value=Settings(_env_file=None,database_path=path)):report=doctor.inspect()
            self.assertIn('error',report['database'])
