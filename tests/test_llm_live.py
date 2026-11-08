"""Valgfri live-integrasjon mot en ekstern OpenAI-kompatibel leverandør.

Kjøres bare når LLM_LIVE_TEST=1. Testen er ikke del av vanlig CI og bruker
syntetiske data, ett kall og ingen logging av nøkkel eller persondata.
"""
import os
import unittest

from app.llm import LlmInterpreter
from app.config import Config


def _live_config():
    return Config(
        app_env="test",
        llm_enabled=True,
        llm_base_url=os.environ.get("LLM_LIVE_BASE_URL", ""),
        llm_model=os.environ.get("LLM_LIVE_MODEL", ""),
        llm_api_key=os.environ.get("LLM_LIVE_API_KEY", ""),
        llm_timeout_s=20.0,
        llm_max_input_chars=500,
    )


@unittest.skipUnless(
    os.environ.get("LLM_LIVE_TEST") == "1"
    and os.environ.get("LLM_LIVE_BASE_URL")
    and os.environ.get("LLM_LIVE_MODEL")
    and os.environ.get("LLM_LIVE_API_KEY"),
    "live LLM-test er ikke eksplisitt aktivert",
)
class LiveGenericProviderTests(unittest.TestCase):
    def test_synthetic_travel_query(self):
        interpreter = LlmInterpreter(_live_config())
        result = interpreter.interpret("Når går bussen fra Skredderåsen?")
        self.assertTrue(result.ok, result.error)
        self.assertIn(result.data["kind"], {"DEPARTURES", "UNKNOWN"})
