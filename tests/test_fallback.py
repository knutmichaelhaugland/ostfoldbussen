"""Trygg fallback: modell nede, ugyldig JSON og timeout skal ikke gi 500 eller oppdiktede svar."""

import json
import tempfile
import unittest

from app.llm import Interpreter, LlmInterpreter
from app.rules import rules_interpret
from tests.helpers import RunningApp


def app_with_llm(responder):
    tmp = tempfile.TemporaryDirectory()
    overrides = {
        "llm_enabled": True, "llm_base_url": "https://llm.example/v1",
        "llm_model": "testmodell", "llm_api_key": "nokkel",
    }
    app = RunningApp(tmp.name, overrides)
    app.__enter__()
    llm = LlmInterpreter(app.config, http_post=responder)
    app.ctx.pipeline.llm = llm
    app.ctx.pipeline.interpreter = Interpreter(rules_interpret, llm)
    return app, tmp


def response(content):
    return {"choices": [{"message": {"content": content}}]}


class FallbackTests(unittest.TestCase):
    def _simulate(self, responder, message="Når kjører bussen fra Skredderåsen?"):
        app, tmp = app_with_llm(responder)
        try:
            result = app.post_json("/api/simulate", {"message": message})
            return result
        finally:
            app.__exit__()
            tmp.cleanup()

    def test_timeout_falls_back_to_rules(self):
        def boom(message):
            raise TimeoutError("timeout")
        response = self._simulate(boom)
        self.assertEqual(response.status, 200)
        payload = response.json()
        self.assertEqual(payload["result_type"], "NO_JOURNEY")
        self.assertEqual(payload["interpretation_source"], "rules_fallback")
        self.assertNotIn("Traceback", payload["sms"]["text"])

    def test_invalid_json_falls_back_to_rules(self):
        response = self._simulate(lambda message: response("ikke json"))
        payload = response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["interpretation_source"], "rules_fallback")

    def test_invalid_schema_falls_back_to_rules(self):
        response = self._simulate(lambda message: response(json.dumps(
            {"kind": "FINN_PÅ", "origin_text": "Oslo"})))
        payload = response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["interpretation_source"], "rules_fallback")

    def test_no_phone_is_sent_to_llm(self):
        seen = []

        def capture(message):
            seen.append(message)
            return response(json.dumps({"kind": "UNKNOWN", "clarification_needed": True}))

        app, tmp = app_with_llm(capture)
        try:
            app.post_json("/api/simulate", {"message": "Når kjører bussen fra Skredderåsen?"})
        finally:
            app.__exit__()
            tmp.cleanup()
        self.assertTrue(seen)
        self.assertFalse(any("+47" in message for message in seen))
