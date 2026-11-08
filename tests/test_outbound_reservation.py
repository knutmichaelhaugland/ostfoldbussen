"""Atomisk kapasitetsreservasjon for utgående SMS."""

import tempfile
import unittest
from datetime import datetime, timezone

from app.db import Database


class OutboundReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(f"{self.tmp.name}/app.db")
        self.db.init()
        self.day = datetime.now(timezone.utc).date().isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, key, segments=1, limit=5):
        return self.db.reserve_outbound_delivery(
            pseudonym=None, idempotency_key=key, daily_limit=limit,
            rate_limit=0, day=self.day, since_iso="1970-01-01", segments=segments,
        )

    def test_reserved_segments_count_against_daily_limit(self):
        delivery_id, reason = self.reserve("r1", segments=3, limit=5)
        self.assertIsNotNone(delivery_id)
        self.assertEqual(reason, "reserved")
        delivery_id2, reason2 = self.reserve("r2", segments=3, limit=5)
        self.assertIsNone(delivery_id2)
        self.assertEqual(reason2, "daily_limit_reached")
        self.assertEqual(self.db.get_counters().get("sms_out"), 3)

    def test_failed_delivery_releases_reservation(self):
        delivery_id, _ = self.reserve("r3", segments=2, limit=3)
        self.db.finish_delivery(delivery_id, "failed")
        self.assertEqual(self.db.get_counters().get("sms_out"), 0)
        delivery_id2, reason = self.reserve("r4", segments=2, limit=3)
        self.assertIsNotNone(delivery_id2)
        self.assertEqual(reason, "reserved")

    def test_unknown_delivery_keeps_reservation(self):
        delivery_id, _ = self.reserve("r5", segments=2, limit=3)
        self.db.finish_delivery(delivery_id, "unknown")
        self.assertEqual(self.db.get_counters().get("sms_out"), 2)
        second, reason = self.reserve("r6", segments=2, limit=3)
        self.assertIsNone(second)
        self.assertEqual(reason, "daily_limit_reached")

    def test_sent_delivery_adjusts_to_actual_segments(self):
        delivery_id, _ = self.reserve("r7", segments=1, limit=5)
        self.db.finish_delivery(delivery_id, "sent", segments=3)
        self.assertEqual(self.db.get_counters().get("sms_out"), 3)


class ReservationMigrationTests(unittest.TestCase):
    def test_old_delivery_table_gets_segments_and_provider_column(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/old.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE deliveries (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "twilio_sid TEXT UNIQUE, request_id INTEGER, pseudonym TEXT, "
                    "status TEXT NOT NULL, idempotency_key TEXT UNIQUE, "
                    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
            db = Database(path)
            db.init()
            with db.connect() as connection:
                cols = {row["name"] for row in connection.execute(
                    "PRAGMA table_info(deliveries)")}
            self.assertIn("segments", cols)
            self.assertIn("provider_message_id", cols)
            self.assertNotIn("twilio_sid", cols)


class FinishDeliveryIdempotenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(f"{self.tmp.name}/app.db")
        self.db.init()
        self.day = datetime.now(timezone.utc).date().isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def _reserve(self, key, segments=1):
        delivery_id, _ = self.db.reserve_outbound_delivery(
            pseudonym=None, idempotency_key=key, daily_limit=10,
            rate_limit=0, day=self.day, since_iso="1970-01-01", segments=segments,
        )
        return delivery_id

    def test_double_failed_only_releases_once(self):
        delivery_id = self._reserve("double-failed")
        self.db.finish_delivery(delivery_id, "failed")
        self.db.finish_delivery(delivery_id, "failed")
        self.assertEqual(self.db.get_counters().get("sms_out"), 0)
        self.assertEqual(self.db.recent_deliveries(1)[0]["status"], "failed")

    def test_double_sent_does_not_double_count(self):
        delivery_id = self._reserve("double-sent")
        self.db.finish_delivery(delivery_id, "sent", segments=1)
        self.db.finish_delivery(delivery_id, "sent", segments=1)
        self.assertEqual(self.db.get_counters().get("sms_out"), 1)

    def test_concurrent_finish_is_idempotent(self):
        import threading
        delivery_id = self._reserve("concurrent-finish")
        threads = [threading.Thread(target=lambda: self.db.finish_delivery(
            delivery_id, "failed")) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(self.db.get_counters().get("sms_out"), 0)


class DailyLimitClosedTests(unittest.TestCase):
    def test_zero_daily_limit_is_not_unlimited(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(f"{tmp}/app.db"); db.init()
            delivery_id, reason = db.reserve_outbound_delivery(
                pseudonym=None, idempotency_key="zero", daily_limit=0,
                rate_limit=0, day="2026-11-07", since_iso="1970-01-01",
            )
            self.assertIsNone(delivery_id)
            self.assertEqual(reason, "daily_limit_disabled")

    def test_unknown_cannot_be_retried_with_same_idempotency_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(f"{tmp}/app.db"); db.init()
            day = datetime.now(timezone.utc).date().isoformat()
            delivery_id, _ = db.reserve_outbound_delivery(
                pseudonym=None, idempotency_key="unknown-key", daily_limit=10,
                rate_limit=0, day=day, since_iso="1970-01-01", segments=1,
            )
            db.finish_delivery(delivery_id, "unknown")
            again, reason = db.reserve_outbound_delivery(
                pseudonym=None, idempotency_key="unknown-key", daily_limit=10,
                rate_limit=0, day=day, since_iso="1970-01-01", segments=1,
            )
            self.assertIsNone(again)
            self.assertEqual(reason, "duplicate")
