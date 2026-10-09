from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from mock_api.app import app


class MockApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')

    def test_known_vendor(self):
        r = self.client.get('/vendor-risk/BrandBoard')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['security_review_status'], 'not_completed')

    def test_forced_outage(self):
        r = self.client.get('/vendor-risk/NimbusAI')
        self.assertEqual(r.status_code, 503)

    # F5 / D-05
    def test_case_and_whitespace_insensitive_returns_canonical_name(self):
        r = self.client.get('/vendor-risk/%20signalwatch%20')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['vendor_name'], 'SignalWatch')

    def test_slash_in_name_is_a_404_not_a_routing_error(self):
        r = self.client.get('/vendor-risk/A%2FB%20Tools')
        self.assertEqual(r.status_code, 404)
        self.assertIn('A/B Tools', r.json()['detail'])

    def test_extra_data_dir_merge_is_per_request(self):
        with mock.patch.dict(os.environ, {'EXTRA_DATA_DIR': ''}):
            self.assertEqual(self.client.get('/vendor-risk/LedgerLens').status_code, 404)
        with mock.patch.dict(os.environ, {'EXTRA_DATA_DIR': 'evals/fixtures'}):
            r = self.client.get('/vendor-risk/LedgerLens')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['security_review_status'], 'not_completed')
            # official records still present
            self.assertEqual(self.client.get('/vendor-risk/BrandBoard').status_code, 200)


if __name__ == '__main__':
    unittest.main()
