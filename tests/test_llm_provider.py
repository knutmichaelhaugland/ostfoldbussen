"""Generisk OpenAI-kompatibel adapter testes mot lokal mock-HTTP-server."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.llm import LlmInterpreter
from app.pipeline import message_hash
from tests.helpers import make_config


class _Handler(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).captured.append({"path": self.path, "body": body,
                                    "headers": dict(self.headers)})
        content = json.dumps({
            "kind": "DEPARTURES", "origin_text": "Skredderåsen",
            "line_number": "22", "time_text": "",
        })
        response = json.dumps({"choices": [{"message": {"content": content}}],
                               "usage": {"prompt_tokens": 11, "completion_tokens": 5}}
                              ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


class GenericLlmHttpTests(unittest.TestCase):
    def setUp(self):
        _Handler.captured = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _config(self, model="generisk-modell", **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        values = dict(llm_enabled=True, llm_base_url=self.base_url,
                      llm_model=model, llm_api_key="test-key")
        values.update(overrides)
        return make_config(tmp.name, **values)

    def test_generic_adapter_posts_utf8_bytes_without_qwen_fields(self):
        interpreter = LlmInterpreter(self._config())
        result = interpreter.interpret("Syntetisk reiseforespørsel æøå")
        self.assertTrue(result.ok)
        self.assertEqual(len(_Handler.captured), 1)
        call = _Handler.captured[0]
        self.assertEqual(call["path"], "/v1/chat/completions")
        self.assertIsInstance(call["body"], bytes)
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual(payload["model"], "generisk-modell")
        self.assertEqual(payload["messages"][1]["content"], "Syntetisk reiseforespørsel æøå")
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(call["headers"].get("Authorization"), "Bearer test-key")

    def test_qwen_specific_reasoning_parameter_is_explicit(self):
        interpreter = LlmInterpreter(self._config(model="qwen3.6-test"))
        self.assertTrue(interpreter.interpret("Syntetisk").ok)
        payload = json.loads(_Handler.captured[0]["body"].decode("utf-8"))
        self.assertEqual(payload["reasoning_effort"], "none")

    def test_input_limit_rejects_before_http(self):
        interpreter = LlmInterpreter(self._config(llm_max_input_chars=4))
        result = interpreter.interpret("12345")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "input_too_long")
        self.assertEqual(_Handler.captured, [])


class MessageHashTests(unittest.TestCase):
    def test_optional_hmac_key_is_deterministic_and_distinct(self):
        unsalted = message_hash("Når går bussen?")
        keyed = message_hash("Når går bussen?", "k" * 32)
        self.assertEqual(unsalted, "")
        self.assertEqual(len(keyed), 64)
        self.assertEqual(keyed, message_hash("Når går bussen?", "k" * 32))


class LlmObservabilityTests(unittest.TestCase):
    def test_attempts_success_tokens_are_counted_separately(self):
        from app.db import Database
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(f"{tmp}/app.db")
            db.init()
            config = make_config(tmp, llm_enabled=True, llm_base_url="http://x/v1",
                                 llm_model="m", llm_api_key="k")
            response = {"choices": [{"message": {"content": json.dumps({
                "kind": "UNKNOWN", "clarification_needed": True})}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
            llm = LlmInterpreter(config, db=db, http_post=lambda message: response)
            self.assertTrue(llm.interpret("Hei").ok)
            counters = db.get_counters()
            self.assertEqual(counters.get("llm_attempts"), 1)
            self.assertEqual(counters.get("llm_success"), 1)
            self.assertEqual(counters.get("llm_input_tokens"), 7)
            self.assertEqual(counters.get("llm_output_tokens"), 3)


class _RedirectHandler(BaseHTTPRequestHandler):
    target_hits = 0
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path.endswith("/chat/completions"):
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
            return
        type(self).target_hits += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class RedirectProviderTests(unittest.TestCase):
    def test_provider_redirect_is_not_followed(self):
        _RedirectHandler.target_hits = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = make_config(
            tmp.name, llm_enabled=True,
            llm_base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
            llm_model="m", llm_api_key="secret-key",
        )
        result = LlmInterpreter(config).interpret("Hei")
        self.assertFalse(result.ok)
        self.assertEqual(_RedirectHandler.target_hits, 0)
