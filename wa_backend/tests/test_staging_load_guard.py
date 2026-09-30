"""Small deterministic fail-closed guard gate; no Locust, DB or network."""
import os
import unittest
from unittest.mock import patch

from scripts.staging_load_guard import (
    ACK,
    assert_actual_target,
    read_staging_load_config,
)


BASE = {
    "WANASAH_LOAD_TEST_ACK": ACK,
    "WANASAH_LOAD_STAGING_URL": "https://staging.wanasah.invalid",
    "WANASAH_LOAD_APPROVED_URL": "https://staging.wanasah.invalid",
    "WANASAH_LOAD_TOKEN_COMPANY_A": "synthetic-a",
    "WANASAH_LOAD_TOKEN_COMPANY_B": "synthetic-b",
    "WANASAH_LOAD_JOB_COMPANY_A": "11111111-1111-4111-8111-111111111111",
    "WANASAH_LOAD_JOB_COMPANY_B": "22222222-2222-4222-8222-222222222222",
}


class StagingLoadGuardTests(unittest.TestCase):
    def check(self, **changes):
        env = dict(BASE)
        env.update(changes)
        with patch.dict(os.environ, env, clear=True):
            return read_staging_load_config()

    def test_explicit_approved_https_staging_only(self):
        config = self.check()
        self.assertEqual(config.job_a, BASE["WANASAH_LOAD_JOB_COMPANY_A"])
        self.assertEqual(config.job_b, BASE["WANASAH_LOAD_JOB_COMPANY_B"])
        assert_actual_target("https://staging.wanasah.invalid/", config)
        with self.assertRaises(RuntimeError):
            assert_actual_target("https://www.wanasah.invalid", config)

    def test_unacknowledged_or_cross_host_or_plaintext_host_denied(self):
        for changes in (
            {"WANASAH_LOAD_TEST_ACK": ""},
            {"WANASAH_LOAD_APPROVED_URL": "https://another.invalid"},
            {"WANASAH_LOAD_STAGING_URL": "http://staging.wanasah.invalid",
             "WANASAH_LOAD_APPROVED_URL": "http://staging.wanasah.invalid"},
            {"WANASAH_LOAD_STAGING_URL": "https://user:pass@staging.wanasah.invalid"},
            {"WANASAH_LOAD_STAGING_URL": "https://staging.wanasah.invalid/login"},
            {"WANASAH_LOAD_TOKEN_COMPANY_A": ""},
            {"WANASAH_LOAD_TOKEN_COMPANY_B": "synthetic-a"},
            {"WANASAH_LOAD_JOB_COMPANY_A": "not-a-uuid"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.check(**changes)

    def test_single_tenant_safe_catalog_mode(self):
        config = self.check(
            WANASAH_LOAD_TOKEN_COMPANY_B="",
            WANASAH_LOAD_JOB_COMPANY_A="",
            WANASAH_LOAD_JOB_COMPANY_B="",
        )
        self.assertIsNone(config.token_b)
        self.assertIsNone(config.job_a)

    def test_imported_locust_source_contains_no_write_calls_or_credentials(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        text = (root / "locustfile.py").read_text(encoding="utf-8")
        self.assertIn("assert_actual_target", text)
        self.assertIn("@events.test_start.add_listener", text)
        self.assertNotIn("self.client.post(", text)
        self.assertNotIn("self.client.put(", text)
        self.assertNotIn("self.client.delete(", text)
        self.assertNotIn('"password":', text.lower())
        self.assertNotIn("company_code", text)


if __name__ == "__main__":
    unittest.main()
