import asyncio
import base64
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from backend.app.config import Settings
from backend.app.main import lifespan
from backend.tests import test_product as product


class AccessTests(unittest.TestCase):
    setUp = product.ProductTests.setUp
    tearDown = product.ProductTests.tearDown
    request = product.ProductTests.request
    routers = product.ProductTests.routers
    protect = True

    def test_private_access_rejects_missing_wrong_and_malformed_credentials(self):
        settings = Settings(_env_file=None, access_username='radar', access_password='fixture-password-12345')
        with patch('backend.app.security.get_settings', return_value=settings):
            for auth in ('', 'Basic not-base64!', 'Bearer wrong', 'Basic ' + base64.b64encode(b'radar:wrong').decode()):
                self.assertEqual(self.request('GET', '/api/sources', headers={'authorization': auth})[0], 401)
            auth = 'Basic ' + base64.b64encode(b'radar:fixture-password-12345').decode()
            self.assertEqual(self.request('GET', '/api/sources', headers={'authorization': auth})[0], 200)

    def test_production_refuses_to_start_without_access_credentials(self):
        async def start():
            with patch('backend.app.main.get_settings', return_value=Settings(_env_file=None, app_env='production', database_path=self.database.path)):
                async with lifespan(FastAPI()):
                    self.fail('Production accepted missing credentials')
        with self.assertRaises(RuntimeError):
            asyncio.run(start())
