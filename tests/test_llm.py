"""LLM-adapter: disabled, schema-validering, fallback og personvern.

Ingen ekte LLM-kall. Adapteren er UTESTET mot ekte provider (ingen nøkkel).
"""

import json
import tempfile
import unittest

from app.config import Config
from app.llm import Interpreter, LlmInterpreter
from prototype.intent import Intent
from tests.helpers import RunningApp, make_config


def llm_config(tmpdir, **overrides):
    values = dict(llm_enabled=True, llm_base_url="https://llm.example/v1", llm_model="testmodell",
                  llm_api_key="nokkel")
    values.update(overrides)
    return make_config(tmpdir, **values)


def valid_llm_response(kind="DEPARTURES", from_text="Skredderåsen", line="22"):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"kind": kind, "from_text": from_text, "to_text": "", "line_code": line,
                         "time_text": ""}
                    )
                }
            }
        ]
    }


class LlmInterpreterTests(unittest.TestCase):
    def test_disabled_makes_no_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)  # LLM_ENABLED=false
            calls = []

            def fake_post(message):
                calls.append(message)
                return valid_llm_response()

            interpreter = LlmInterpreter(config, http_post=fake_post)
            result = interpreter.interpret("Hei")
            self.assertFalse(result.ok)
            self.assertEqual(result.error, "disabled")
            self.assertEqual(calls, [])

    def test_valid_response_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            interpreter = LlmInterpreter(config, http_post=lambda message: valid_llm_response())
            result = interpreter.interpret("Når går bussen?")
            self.assertTrue(result.ok)
            self.assertEqual(result.data["kind"], "DEPARTURES")
            self.assertEqual(result.data["line_code"], "22")

    def test_invalid_kind_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            response = {"choices": [{"message": {"content": '{"kind": "SLEEP"}'}}]}
            result = LlmInterpreter(config, http_post=lambda message: response).interpret("x")
            self.assertFalse(result.ok)
            self.assertEqual(result.error, "schema_invalid")

    def test_broken_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            response = {"choices": [{"message": {"content": "ikke json"}}]}
            result = LlmInterpreter(config, http_post=lambda message: response).interpret("x")
            self.assertFalse(result.ok)

    def test_exception_is_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)

            def boom(message):
                raise TimeoutError("timeout")

            result = LlmInterpreter(config, http_post=boom).interpret("x")
            self.assertFalse(result.ok)
            self.assertEqual(result.error, "TimeoutError")


class RulesFirstTests(unittest.TestCase):
    def rules(self, message, now=None):
        from app.rules import rules_interpret

        return rules_interpret(message, now=now)

    def test_rules_first_avoids_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            calls = []
            llm = LlmInterpreter(config, http_post=lambda message: calls.append(message) or valid_llm_response())
            interpreter = Interpreter(self.rules, llm)
            intent, source = interpreter.interpret("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(source, "rules")
            self.assertEqual(intent.kind, "DEPARTURES")
            self.assertEqual(calls, [])

    def test_llm_used_for_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            llm = LlmInterpreter(config, http_post=lambda message: valid_llm_response())
            interpreter = Interpreter(self.rules, llm)
            intent, source = interpreter.interpret("Heisann, hva skjer?")
            self.assertEqual(source, "llm")
            self.assertEqual(intent.kind, "DEPARTURES")
            self.assertEqual(intent.from_text, "Skredderåsen")

    def test_fallback_to_rules_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            broken = {"choices": [{"message": {"content": "tull"}}]}
            llm = LlmInterpreter(config, http_post=lambda message: broken)
            interpreter = Interpreter(self.rules, llm)
            intent, source = interpreter.interpret("Heisann")
            self.assertEqual(source, "rules_fallback")
            self.assertEqual(intent.kind, "UNKNOWN")

    def test_fallback_to_rules_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = llm_config(tmp)
            llm = LlmInterpreter(config, http_post=lambda message: (_ for _ in ()).throw(OSError("nede")))
            interpreter = Interpreter(self.rules, llm)
            intent, source = interpreter.interpret("Heisann")
            self.assertEqual(source, "rules_fallback")
            self.assertEqual(intent.kind, "UNKNOWN")


class LlmPipelinePrivacyTests(unittest.TestCase):
    def test_phone_never_sent_to_llm(self):
        calls = []

        def llm_post(message):
            calls.append(message)
            return valid_llm_response(kind="UNKNOWN", from_text="", line="")

        with tempfile.TemporaryDirectory() as tmp:
            config_overrides = dict(
                llm_enabled=True,
                llm_base_url="https://llm.example/v1",
                llm_model="testmodell",
                llm_api_key="nokkel",
            )
            app = RunningApp(tmp, config_overrides)
            app.ctx.pipeline.llm = LlmInterpreter(app.config, http_post=llm_post)
            from app.llm import Interpreter
            from app.rules import rules_interpret
            app.ctx.pipeline.interpreter = Interpreter(rules_interpret, app.ctx.pipeline.llm)
            with app:
                app.ctx.pipeline.run("Heisann", channel="api")
                self.assertEqual(len(calls), 1)
                self.assertNotIn("98765432", calls[0])
                self.assertNotIn("+47", calls[0])
