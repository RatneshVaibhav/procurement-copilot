from __future__ import annotations

import os
import unittest
from datetime import date
from unittest import mock

from src.config import get_reference_date, get_settings, parse_reference_date


class ReferenceDateTests(unittest.TestCase):
    def test_policy_file_reference_date(self):
        self.assertEqual(get_reference_date(), date(2026, 9, 30))

    def test_policy_regex(self):
        text = "**Data snapshot / evaluation reference date:** 2026-09-30  \n"
        self.assertEqual(parse_reference_date(text), date(2026, 9, 30))

    def test_readme_wording_fallback(self):
        readme = "**Reference date for date-based policy checks: 2026-09-30.** Use this snapshot date"
        self.assertEqual(parse_reference_date("no date here", readme), date(2026, 9, 30))

    def test_module_alias(self):
        from src import config
        self.assertEqual(config.REFERENCE_DATE, date(2026, 9, 30))
        self.assertEqual(config.POLICY_VERSION, "2026.09")

    def test_no_date_raises(self):
        with self.assertRaises(RuntimeError):
            parse_reference_date("nothing", "still nothing")


class SettingsTests(unittest.TestCase):
    def test_read_at_call_time(self):
        with mock.patch.dict(os.environ, {"VENDOR_RISK_BASE_URL": "http://127.0.0.1:9999/"}):
            self.assertEqual(get_settings().vendor_risk_base_url, "http://127.0.0.1:9999")
        with mock.patch.dict(os.environ, {"VENDOR_RISK_BASE_URL": "http://127.0.0.1:8123"}):
            self.assertEqual(get_settings().vendor_risk_base_url, "http://127.0.0.1:8123")

    def test_provider_defaults(self):
        env = {"LLM_PROVIDER": "groq", "MODEL_NAME": "", "LLM_MIN_INTERVAL_SECONDS": ""}
        with mock.patch.dict(os.environ, env):
            s = get_settings()
        self.assertEqual(s.model_name, "openai/gpt-oss-20b")
        self.assertEqual(s.llm_min_interval_seconds, 2.5)
        self.assertEqual(s.llm_base_url, "https://api.groq.com/openai/v1")

    def test_unknown_provider_is_unconfigured(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "nope", "GROQ_API_KEY": "x"}):
            self.assertFalse(get_settings().llm_configured)

    def test_blank_reasoning_effort_is_not_sent(self):
        with mock.patch.dict(os.environ, {"LLM_REASONING_EFFORT": ""}):
            self.assertIsNone(get_settings().llm_reasoning_effort)

    def test_simulate_outage_flag(self):
        with mock.patch.dict(os.environ, {"LLM_SIMULATE_OUTAGE": "1"}):
            self.assertTrue(get_settings().llm_simulate_outage)
        with mock.patch.dict(os.environ, {"LLM_SIMULATE_OUTAGE": ""}):
            self.assertFalse(get_settings().llm_simulate_outage)


if __name__ == "__main__":
    unittest.main()
