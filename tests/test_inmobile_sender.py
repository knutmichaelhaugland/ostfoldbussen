"""inMobile utgående SMS: normalisering, sperre og payload."""

import unittest

from app.config import Config
from app.db import Database
from app.inmobile_sender import InmobileSender, normalize_number


class SenderTests(unittest.TestCase):
    def _db(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(f"{tmp.name}/app.db")
        db.init()
        return db

    def test_normalize_norwegian_number(self):
        self.assertEqual(normalize_number("+47 900 00 000"), "4790000000")
        self.assertEqual(normalize_number("90000000"), "4790000000")
        self.assertEqual(normalize_number("004790000000"), "4790000000")

    def test_suppressed_when_disabled(self):
        config = Config(inmobile_outbound_enabled=False)
        sent = []
        sender = InmobileSender(config, self._db(), http_post=lambda *a: sent.append(a) or {})
        result = sender.send("4790000000", "Hei")
        self.assertTrue(result.suppressed)
        self.assertFalse(result.sent)
        self.assertEqual(sent, [])

    def test_payload_when_enabled(self):
        config = Config(inmobile_outbound_enabled=True, inmobile_api_key="key",
                        inmobile_from="4700000000", daily_sms_limit=100)
        calls = []

        def fake_post(url, payload, key):
            calls.append((url, payload, key))
            return {"results": [{"messageId": "m1", "smsCount": 1}]}

        sender = InmobileSender(config, self._db(), http_post=fake_post)
        result = sender.send("90000000", "Hei på deg")
        self.assertTrue(result.sent)
        self.assertEqual(result.message_id, "m1")
        url, payload, key = calls[0]
        self.assertTrue(url.endswith("/v4/sms/outgoing"))
        self.assertEqual(key, "key")
        message = payload["messages"][0]
        self.assertEqual(message["to"], "4790000000")
        self.assertEqual(message["text"], "Hei på deg")
        self.assertEqual(message["from"], "4700000000")


    def test_empty_provider_response_is_not_sent(self):
        config = Config(inmobile_outbound_enabled=True, inmobile_api_key="key",
                        inmobile_from="4700000000", daily_sms_limit=100)
        db = self._db()
        sender = InmobileSender(config, db, http_post=lambda *a: {"results": []})
        result = sender.send("90000000", "Hei")
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "invalid_response")
        # Ukjent levering beholder reservasjonen for å unngå kostnadsoverskridelse.
        self.assertEqual(db.get_counters().get("sms_out"), 1)

    def test_duplicate_idempotency_key_is_suppressed(self):
        config = Config(inmobile_outbound_enabled=True, inmobile_api_key="key",
                        inmobile_from="4700000000", daily_sms_limit=100)
        calls = []
        def fake_post(url, payload, key):
            calls.append(1)
            return {"results": [{"messageId": "m1", "smsCount": 1}]}
        sender = InmobileSender(config, self._db(), http_post=fake_post)
        first = sender.send("90000000", "Hei", idempotency_key="same-key")
        second = sender.send("90000000", "Hei", idempotency_key="same-key")
        self.assertTrue(first.sent)
        self.assertFalse(second.sent)
        self.assertTrue(second.suppressed)
        self.assertEqual(second.reason, "duplicate")
        self.assertEqual(len(calls), 1)

    def test_sms_segments_are_counted(self):
        config = Config(inmobile_outbound_enabled=True, inmobile_api_key="key",
                        inmobile_from="4700000000", daily_sms_limit=100)
        db = self._db()
        sender = InmobileSender(config, db, http_post=lambda *a: {
            "results": [{"messageId": "m1", "smsCount": 3}]})
        result = sender.send("90000000", "Lang melding")
        self.assertTrue(result.sent)
        self.assertEqual(result.segments, 3)
        self.assertEqual(db.get_counters().get("sms_out"), 3)
        self.assertEqual(db.get_delivery("m1")["provider_message_id"], "m1")

    def test_parallel_senders_respect_rate_limit(self):
        import threading
        config = Config(inmobile_outbound_enabled=True, inmobile_api_key="key",
                        inmobile_from="4700000000", daily_sms_limit=100,
                        rate_limit_per_hour=1)
        import tempfile
        from app.db import Database
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(f"{tmp.name}/app.db")
        db.init()
        calls = []
        def fake_post(url, payload, key):
            calls.append(1)
            import time
            time.sleep(0.15)
            return {"results": [{"messageId": "m", "smsCount": 1}]}
        sender = InmobileSender(config, db, http_post=fake_post)
        results = []
        threads = [threading.Thread(target=lambda: results.append(
            sender.send("90000000", "Hei", pseudonym="p1"))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(1 for r in results if r.sent), 1)
        self.assertEqual(sum(1 for r in results if r.suppressed), 1)


class DailyCapacityConcurrencyTests(unittest.TestCase):
    def test_parallel_sends_never_exceed_daily_limit(self):
        import threading
        config = Config(inmobile_outbound_enabled=True, inmobile_api_key="key",
                        inmobile_from="4700000000", daily_sms_limit=3,
                        rate_limit_per_hour=100)
        import tempfile
        from app.db import Database
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(f"{tmp.name}/app.db")
        db.init()
        calls = []
        lock = threading.Lock()
        def fake_post(url, payload, key):
            with lock:
                calls.append(1)
            import time
            time.sleep(0.05)
            return {"results": [{"messageId": "m", "smsCount": 1}]}
        sender = InmobileSender(config, db, http_post=fake_post)
        results = []
        threads = [threading.Thread(target=lambda: results.append(
            sender.send("90000000", "Hei"))) for _ in range(10)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum(1 for r in results if r.sent), 3)
        self.assertEqual(db.get_counters().get("sms_out"), 3)
