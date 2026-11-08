"""Bineric-adapter: fail-closed, parsing, budsjett og retry."""
import json
import tempfile
import unittest
import urllib.error

from app.bineric_llm import BinericLlm
from app.config import Config
from app.db import Database


def cfg(**overrides):
    values = dict(app_env="test", bineric_enabled=True, bineric_api_key="key",
                  bineric_base_url="https://example.invalid/v1", bineric_model="qwen-3-235b",
                  bineric_daily_budget_usd=5.0, bineric_max_retries=0)
    values.update(overrides)
    return Config(**values)


class BinericAdapterTests(unittest.TestCase):
    def _db(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(f"{tmp.name}/app.db")
        db.init()
        return db

    def test_disabled_without_flag(self):
        llm = BinericLlm(cfg(bineric_enabled=False), self._db())
        self.assertFalse(llm.enabled)
        result = llm.interpret("Når går bussen?")
        self.assertFalse(result.ok)

    def test_valid_response_is_parsed(self):
        payload = {"choices": [{"message": {"content": json.dumps({
            "kind": "DEPARTURES", "origin_text": "Skredderåsen",
            "destination_text": "", "line_number": "22", "time_text": "",
            "clarification_needed": False})}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
        llm = BinericLlm(cfg(), self._db(), http_post=lambda body: payload)
        result = llm.interpret("Når går buss 22 fra Skredderåsen?")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["kind"], "DEPARTURES")

    def test_budget_exhausted_fails_closed(self):
        db = self._db()
        db.increment_counter("bineric_cost_micro_usd", 6_000_000)
        llm = BinericLlm(cfg(bineric_daily_budget_usd=5.0), db,
                         http_post=lambda body: {})
        result = llm.interpret("Når går bussen?")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "budget_exhausted")

    def test_429_is_retried_then_succeeds(self):
        calls = []
        def post(body):
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError("url", 429, "Too Many", {"Retry-After": "0"}, None)
            return {"choices": [{"message": {"content": json.dumps({
                "kind": "UNKNOWN", "clarification_needed": True})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        llm = BinericLlm(cfg(bineric_max_retries=1), self._db(), http_post=post,
                         sleep=lambda s: None)
        result = llm.interpret("Hei")
        self.assertTrue(result.ok)
        self.assertEqual(len(calls), 2)


    def test_parallel_calls_cannot_overspend_budget(self):
        import threading, time
        payload = {"choices": [{"message": {"content": json.dumps({
            "kind": "UNKNOWN", "clarification_needed": True})}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
        calls = []
        def post(body):
            calls.append(1)
            time.sleep(0.1)
            return payload
        llm = BinericLlm(cfg(bineric_daily_budget_usd=0.0006), self._db(), http_post=post)
        results = []
        threads = [threading.Thread(target=lambda: results.append(llm.interpret("Hei")))
                   for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(1 for result in results if result.ok), 1)
        self.assertEqual(sum(1 for result in results if result.error == "budget_exhausted"), 1)


class BinericBudgetFailureTests(unittest.TestCase):
    def _db(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(f"{tmp.name}/app.db")
        db.init()
        return db

    def test_4xx_releases_reserved_budget(self):
        db = self._db()
        def bad(body):
            raise urllib.error.HTTPError("url", 400, "bad", {}, None)
        llm = BinericLlm(cfg(), db, http_post=bad)
        result = llm.interpret("Hei")
        self.assertFalse(result.ok)
        self.assertEqual(db.get_counters().get("bineric_cost_micro_usd", 0), 0)

    def test_timeout_retains_ambiguous_budget(self):
        db = self._db()
        def timeout(body):
            raise TimeoutError("timeout")
        llm = BinericLlm(cfg(bineric_max_retries=0), db, http_post=timeout)
        result = llm.interpret("Hei")
        self.assertFalse(result.ok)
        self.assertGreater(db.get_counters().get("bineric_cost_micro_usd", 0), 0)

    def test_input_limit_rejects_before_budget_or_http(self):
        db = self._db()
        llm = BinericLlm(cfg(llm_max_input_chars=3), db,
                         http_post=lambda body: self.fail("skal ikke kalles"))
        result = llm.interpret("12345")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "input_too_long")
        self.assertEqual(db.get_counters().get("bineric_cost_micro_usd", 0), 0)


class BinericDbBudgetConcurrencyTests(unittest.TestCase):
    def test_atomic_counter_reservation_never_overspends(self):
        import tempfile
        import threading
        from app.db import Database
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(f"{tmp.name}/app.db")
        db.init()
        results = []
        threads = [threading.Thread(target=lambda: results.append(
            db.reserve_daily_counter("test_budget", 1, 3))) for _ in range(10)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(results.count(True), 3)
        self.assertEqual(db.get_counters().get("test_budget"), 3)
