"""Enhetstester: SQLite (WAL), skjema, TTL, idempotens og tellere."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.db import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        self.db.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_wal_mode(self):
        with self.db.connect() as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_schema_tables_exist(self):
        with self.db.connect() as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        for table in ("requests", "conversation_context", "deliveries", "daily_counters"):
            self.assertIn(table, names)

    def test_record_request_and_counts(self):
        request_id = self.db.record_request(
            created_at=datetime.now(timezone.utc).isoformat(),
            sender_pseudonym="p" * 64,
            message_hash="h" * 64,
            intent="DEPARTURES",
            result_type="VALID_SUITABLE",
            status="ok",
            latency_ms=12,
            build_sha="sha",
            error_category=None,
            channel="api",
        )
        self.assertGreater(request_id, 0)
        counts = self.db.request_counts()
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["by_result_type"]["VALID_SUITABLE"], 1)
        row = self.db.recent_requests(10)[0]
        self.assertEqual(row["intent"], "DEPARTURES")
        self.assertNotIn("message", row)
        self.assertNotIn("phone", row)

    def test_conversation_ttl(self):
        now = datetime.now(timezone.utc)
        self.db.save_conversation("user1", {"kind": "TRIP"}, ttl_minutes=30)
        self.assertEqual(self.db.load_conversation("user1", now)["kind"], "TRIP")
        later = now + timedelta(minutes=31)
        self.assertIsNone(self.db.load_conversation("user1", later))
        self.assertGreaterEqual(self.db.purge_expired_conversations(later), 0)

    def test_delivery_idempotency(self):
        first, created = self.db.add_delivery(
            provider_message_id=None,
            request_id=1,
            pseudonym="p",
            status="suppressed",
            idempotency_key="inbound:SM1",
        )
        self.assertTrue(created)
        second, created_again = self.db.add_delivery(
            provider_message_id=None,
            request_id=2,
            pseudonym="p",
            status="suppressed",
            idempotency_key="inbound:SM1",
        )
        self.assertFalse(created_again)
        self.assertEqual(first, second)

    def test_delivery_status_update(self):
        self.db.add_delivery(
            provider_message_id="SM1", request_id=1, pseudonym=None, status="sent", idempotency_key="outbound:SM1"
        )
        self.assertTrue(self.db.update_delivery_status("SM1", "delivered"))
        self.assertEqual(self.db.get_delivery("SM1")["status"], "delivered")
        self.assertFalse(self.db.update_delivery_status("ukjent", "delivered"))

    def test_counters(self):
        self.assertEqual(self.db.get_counters("2026-11-06"), {})
        self.db.increment_counter("requests", day="2026-11-06")
        self.db.increment_counter("requests", day="2026-11-06")
        self.db.increment_counter("sms_out", day="2026-11-06")
        counters = self.db.get_counters("2026-11-06")
        self.assertEqual(counters["requests"], 2)
        self.assertEqual(counters["sms_out"], 1)

    def test_outbound_count_excludes_suppressed(self):
        self.db.add_delivery(
            provider_message_id="SM1", request_id=None, pseudonym="p", status="sent", idempotency_key="a"
        )
        self.db.add_delivery(
            provider_message_id=None, request_id=None, pseudonym="p", status="suppressed", idempotency_key="b"
        )
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(self.db.outbound_count_since("p", since), 1)

    def test_healthcheck(self):
        self.assertTrue(self.db.healthcheck())


if __name__ == "__main__":
    unittest.main()
