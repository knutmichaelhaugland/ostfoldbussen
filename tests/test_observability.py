"""Observabilitetsmatrise §9 og retention (§10)."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import RunningApp, invite, make_config


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_has_all_14_signals(self):
        with RunningApp(self.tmp.name) as app:
            obs = app.ctx.observability.snapshot()
        ids = [signal["id"] for signal in obs["signals"]]
        self.assertEqual(ids, [f"OBS-{i:02d}" for i in range(1, 15)])
        by_id = {signal["id"]: signal for signal in obs["signals"]}
        self.assertEqual(by_id["OBS-05"]["state"], "NOT CONFIGURED")  # VP
        self.assertEqual(by_id["OBS-06"]["state"], "NOT CONFIGURED")  # LLM
        self.assertEqual(by_id["OBS-07"]["state"], "NOT CONFIGURED")  # inMobile uten credentials
        self.assertEqual(by_id["OBS-09"]["state"], "UNKNOWN")          # kostnad uten priser

    def test_inmobile_enabled_without_credentials_is_pending(self):
        with RunningApp(self.tmp.name, {"inmobile_outbound_enabled": True}) as app:
            obs = app.ctx.observability.snapshot()
        by_id = {signal["id"]: signal for signal in obs["signals"]}
        self.assertEqual(by_id["OBS-07"]["state"], "PENDING PROVISIONING")
        self.assertEqual(by_id["OBS-14"]["state"], "PENDING PROVISIONING")

    def test_admin_health_shows_obs_table(self):
        with RunningApp(self.tmp.name) as app:
            _, cookies = app.login()
            page = app.get("/admin/health", cookies=cookies)
        self.assertEqual(page.status, 200)
        for obs_id in (f"OBS-{i:02d}" for i in range(1, 15)):
            self.assertIn(obs_id, page.text)

    def test_security_events_increment_counters(self):
        with RunningApp(
            self.tmp.name,
            {
                "inmobile_webhook_enabled": True,
                "inmobile_webhook_key_id": "kid",
                "inmobile_webhook_public_key": "pk",
            },
        ) as app:
            app.request(
                "POST", "/api/webhooks/inmobile", body=b"{}",
                headers={"Content-Type": "application/json"},
            )
            counters = app.ctx.db.get_counters()
            self.assertEqual(counters.get("security_invalid_signature"), 1)

    def test_rate_limit_increments_counter(self):
        with RunningApp(self.tmp.name, {"simulate_rate_limit_per_hour": 1}) as app:
            app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            counters = app.ctx.db.get_counters()
            self.assertEqual(counters.get("security_rate_limited"), 1)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = invite(self.tmp.name + "/app.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_purge_removes_old_rows_but_keeps_open_reviews(self):
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        very_old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        self.db.record_request(
            created_at=old, sender_pseudonym="p", message_hash="h", intent="TRIP",
            result_type="NO_JOURNEY", status="ok", latency_ms=1,
            build_sha="sha", error_category=None, channel="api",
        )
        self.db.record_request(
            created_at=new, sender_pseudonym="p2", message_hash="h2", intent="TRIP",
            result_type="VALID_SUITABLE", status="ok", latency_ms=1,
            build_sha="sha", error_category=None, channel="api",
        )
        open_old = self.db.add_error_review(
            created_at=very_old, request_id=None, category="x", pseudonym_ref="p",
            place_ids=[], failure_stage="entur", build_sha="sha",
        )
        closed_old = self.db.add_error_review(
            created_at=very_old, request_id=None, category="y", pseudonym_ref="p",
            place_ids=[], failure_stage="entur", build_sha="sha",
        )
        self.db.update_error_review(closed_old, "FIXED", "ok")
        deleted = self.db.purge_retention(
            requests_days=30, deliveries_days=30, reviews_days=90,
            now=datetime.now(timezone.utc).isoformat(),
        )
        self.assertEqual(deleted["requests"], 1)
        self.assertEqual(deleted["error_reviews"], 1)  # kun FIXED, ikke OPEN
        self.assertEqual(self.db.request_counts()["total"], 1)
        statuses = {row["id"]: row["review_status"] for row in self.db.recent_error_reviews(10)}
        self.assertEqual(statuses.get(open_old), "OPEN")

    def test_retention_zero_disables(self):
        old = (datetime.now(timezone.utc) - timedelta(days=999)).isoformat()
        self.db.record_request(
            created_at=old, sender_pseudonym="p", message_hash="h", intent="TRIP",
            result_type="NO_JOURNEY", status="ok", latency_ms=1,
            build_sha="sha", error_category=None, channel="api",
        )
        self.db.purge_retention(requests_days=0, deliveries_days=0, reviews_days=0)
        self.assertEqual(self.db.request_counts()["total"], 1)


class ObservabilityShapeTests(unittest.TestCase):
    def test_every_signal_has_four_fields_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            signals = app.ctx.observability.snapshot()["signals"]
        for signal in signals:
            self.assertEqual(set(signal), {"id", "name", "state", "detail"})
            self.assertIsInstance(signal["detail"], str)


class RetentionInmobileRequestsTests(unittest.TestCase):
    def test_old_inmobile_webhook_rows_are_purged(self):
        import tempfile
        from app.db import Database, utc_now
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(f"{tmp}/app.db"); db.init()
            with db.connect() as connection:
                connection.execute(
                    "INSERT INTO inmobile_webhook_requests "
                    "(request_id, received_at, status) VALUES (?,?,?)",
                    ("old-req", "2000-01-01T00:00:00+00:00", "completed"),
                )
            deleted = db.purge_retention(
                requests_days=1, deliveries_days=1, reviews_days=1,
                now=utc_now(),
            )
            self.assertEqual(deleted.get("inmobile_webhook_requests"), 1)
