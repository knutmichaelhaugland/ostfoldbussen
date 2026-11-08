"""Kontekstbehandling: rene oppfølginger skal bruke historikk, ikke LLM eller feil sted."""

import json
import tempfile
import unittest

from app.llm import Interpreter, LlmInterpreter
from app.rules import rules_interpret
from tests.helpers import RunningApp


def followup_app(overrides=None, http=None):
    tmp = tempfile.TemporaryDirectory()
    calls = []

    def fake_post(message):
        calls.append(message)
        return {"choices": [{"message": {"content": json.dumps({
            "kind": "UNKNOWN", "clarification_needed": True,
        })}}]}

    overrides = dict(overrides or {})
    overrides.setdefault("llm_enabled", True)
    overrides.setdefault("llm_base_url", "https://llm.example/v1")
    overrides.setdefault("llm_model", "testmodell")
    overrides.setdefault("llm_api_key", "nokkel")
    app = RunningApp(tmp.name, overrides)
    app.__enter__()
    llm = LlmInterpreter(app.config, http_post=http or fake_post)
    app.ctx.pipeline.interpreter = Interpreter(rules_interpret, llm)
    app.ctx.pipeline.llm = llm
    return app, calls, tmp


class ContextTests(unittest.TestCase):
    def test_followup_uses_context_without_llm_call(self):
        app, calls, tmp = followup_app()
        try:
            first = app.post_json("/api/simulate", {
                "message": "Skredderåsen til Refsnes", "conversation_id": "c1"})
            self.assertEqual(first.json()["result_type"], "VALID_SUITABLE")
            calls.clear()
            second = app.post_json("/api/simulate", {
                "message": "hva med en time senere?", "conversation_id": "c1"})
            payload = second.json()
            self.assertEqual(payload["interpretation_source"], "context")
            self.assertEqual(payload["intent"]["kind"], "TRIP")
            self.assertIn("skredder", payload["intent"]["from_text"].lower())
            self.assertIn("refsnes", payload["intent"]["to_text"].lower())
            self.assertEqual(calls, [])  # ingen LLM-kall for ren oppfølging
        finally:
            app.__exit__()
            tmp.cleanup()

    def test_explicit_new_place_overrides_history(self):
        app, calls, tmp = followup_app()
        try:
            app.post_json("/api/simulate", {
                "message": "Skredderåsen til Refsnes", "conversation_id": "c1"})
            second = app.post_json("/api/simulate", {
                "message": "Når går bussen fra Moss bussterminal?",
                "conversation_id": "c1"})
            payload = second.json()
            self.assertEqual(payload["result_type"], "VALID_SUITABLE")
            self.assertEqual(payload["intent"]["kind"], "DEPARTURES")
            self.assertEqual((payload["places"]["from"] or {}).get("name"), "Moss bussterminal")
        finally:
            app.__exit__()
            tmp.cleanup()

    def test_context_does_not_leak_between_conversations(self):
        app, calls, tmp = followup_app()
        try:
            app.post_json("/api/simulate", {
                "message": "Skredderåsen til Refsnes", "conversation_id": "c1"})
            second = app.post_json("/api/simulate", {
                "message": "hva med en time senere?", "conversation_id": "c2"})
            payload = second.json()
            self.assertNotEqual(payload["interpretation_source"], "context")
            self.assertIn(payload["result_type"], {"NO_JOURNEY", "TECHNICAL_ERROR"})
        finally:
            app.__exit__()
            tmp.cleanup()

    def test_tomorrow_followup_shifts_date(self):
        app, calls, tmp = followup_app()
        try:
            first = app.post_json("/api/simulate", {
                "message": "Skredderåsen til Refsnes", "conversation_id": "c1"})
            from datetime import datetime
            first_date = (first.json()["intent"]["target_datetime"] or "")[:10]
            second = app.post_json("/api/simulate", {
                "message": "og i morgen?", "conversation_id": "c1"})
            payload = second.json()
            self.assertEqual(payload["interpretation_source"], "context")
            second_date = (payload["intent"]["target_datetime"] or "")[:10]
            if first_date and second_date:
                self.assertGreater(second_date, first_date)
        finally:
            app.__exit__()
            tmp.cleanup()
