"""Проверки санитайзера LLM, единого флага включения и защиты HTTP-заголовков."""
import os
import unittest
from unittest import mock

from src import reviewer
from src.llm_client import LLMClient, LLMError


class ReviewerSanitizeTest(unittest.TestCase):
    def test_accepts_only_whitelisted_values(self):
        raw = {
            "corrections": {"iso_group": "m", "operation": "roughing", "insert_shape": "X", "clearance_angle": "zzz",
                            "size_code": "12", "corner_radius_mm": 0.8, "category": "turning_insert"},
            "questions": ["материал?", "обработка?", "форма?", "лишний"],
            "reason": "ok",
        }
        got = reviewer.Reviewer.sanitize(raw)
        self.assertEqual(got["corrections"]["iso_group"], "M")
        self.assertEqual(got["corrections"]["operation"], "roughing")
        self.assertEqual(got["corrections"]["size_code"], "12")
        self.assertAlmostEqual(got["corrections"]["corner_radius_mm"], 0.8)
        self.assertNotIn("insert_shape", got["corrections"])
        self.assertNotIn("clearance_angle", got["corrections"])
        self.assertEqual(len(got["questions"]), 3)

    def test_out_of_range_radius_is_dropped(self):
        got = reviewer.Reviewer.sanitize({"corrections": {"corner_radius_mm": 99}})
        self.assertNotIn("corner_radius_mm", got["corrections"])


class ReviewEnabledTest(unittest.TestCase):
    def test_default_is_enabled(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADVISOR_DISABLE_LLM", None)
            os.environ.pop("REVIEW_ENABLED", None)
            self.assertTrue(reviewer.review_enabled())

    def test_each_flag_disables(self):
        for key in ("ADVISOR_DISABLE_LLM", "REVIEW_ENABLED"):
            with mock.patch.dict(os.environ, {key: "1" if key == "ADVISOR_DISABLE_LLM" else "0"}):
                self.assertFalse(reviewer.review_enabled())

    def test_default_sample_rate_is_15_percent(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUDIT_SAMPLE_RATE", None)
            os.environ.pop("REVIEW_SAMPLE_RATE", None)
            self.assertAlmostEqual(reviewer.Reviewer(client=None).sample_rate, 0.15)


class LlmHeaderTest(unittest.TestCase):
    def test_non_ascii_key_fails_before_network(self):
        c = LLMClient()
        c.api_key = "ваш_ключ_кириллицей"
        c.base_url = "http://127.0.0.1:1/v1"
        c.models = ["m"]
        with self.assertRaises(LLMError) as ctx:
            c._call("m", [{"role": "user", "content": "x"}], 0.0, 10, 1)
        self.assertIn("не-ASCII", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
