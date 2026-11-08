"""Kontrakttester for POST /api/simulate (privat testside)."""

import http.client
import json
import tempfile
import unittest
from datetime import datetime

from tests.helpers import (
    FakeEnturClient,
    RunningApp,
    departure_call,
    departure_payload,
)


class SimulateApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = RunningApp(cls.tmp.name)
        cls.app.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.app.__exit__()
        cls.tmp.cleanup()

    def test_departures_question_full_trace(self):
        response = self.app.post_json(
            "/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"}
        )
        self.assertEqual(response.status, 200)
        payload = response.json()
        for key in (
            "request_id",
            "intent",
            "places",
            "result_type",
            "latency_ms",
            "warnings",
            "sms",
            "build_sha",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["result_type"], "VALID_SUITABLE")
        self.assertEqual(payload["intent"]["kind"], "DEPARTURES")
        self.assertEqual(payload["places"]["from"]["county_id"], "KVE:TopographicPlace:31")
        self.assertEqual(payload["sms"]["segments"]["encoding"], "GSM-7")
        self.assertGreaterEqual(payload["sms"]["segments"]["segments"], 1)

    def test_trip_question_full_trace(self):
        response = self.app.post_json(
            "/api/simulate", {"message": "Hvordan kommer jeg fra Skredderåsen til Refsnes?"}
        )
        self.assertEqual(response.status, 200)
        payload = response.json()
        self.assertEqual(payload["result_type"], "VALID_SUITABLE")
        self.assertTrue(payload["recommended"])
        self.assertIn("selected", payload)
        self.assertIn("itineraries", payload)
        self.assertEqual(payload["selected"]["recommended"], True)

    def test_conversation_id_reuses_context(self):
        first = self.app.post_json(
            "/api/simulate",
            {"message": "Hvordan kommer jeg fra Skredderåsen til Refsnes?", "conversation_id": "c1"},
        )
        self.assertEqual(first.status, 200)
        second = self.app.post_json(
            "/api/simulate", {"message": "Når går bussen?", "conversation_id": "c1"}
        )
        self.assertEqual(second.status, 200)
        self.assertEqual(second.json()["places"]["from"]["id"], "NSR:StopPlace:2636")

    def test_invalid_json(self):
        response = self.app.request(
            "POST",
            "/api/simulate",
            body=b"{ikke json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(response.json()["error"], "invalid_json")

    def test_wrong_content_type(self):
        response = self.app.request(
            "POST",
            "/api/simulate",
            body=json.dumps({"message": "hei"}).encode(),
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(response.status, 415)

    def test_missing_message(self):
        response = self.app.post_json("/api/simulate", {"melding": "hei"})
        self.assertEqual(response.status, 400)
        self.assertEqual(response.json()["error"], "message_required")

    def test_empty_message(self):
        response = self.app.post_json("/api/simulate", {"message": "   "})
        self.assertEqual(response.status, 400)

    def test_message_too_long(self):
        response = self.app.post_json("/api/simulate", {"message": "a" * 2000})
        self.assertEqual(response.status, 400)
        self.assertEqual(response.json()["error"], "message_too_long")

    def test_body_too_large(self):
        response = self.app.request(
            "POST",
            "/api/simulate",
            body=b"x" * 9000,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 413)

    def test_invalid_conversation_id(self):
        response = self.app.post_json(
            "/api/simulate", {"message": "hei", "conversation_id": "x" * 100}
        )
        self.assertEqual(response.status, 400)

    def test_missing_content_length(self):
        connection = http.client.HTTPConnection(self.app.host, self.app.port, timeout=10)
        connection.putrequest("POST", "/api/simulate")
        connection.putheader("Content-Type", "application/json")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 411)
        response.read()
        connection.close()

    def test_no_store_and_build_header(self):
        response = self.app.post_json(
            "/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"}
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-build-sha"], "testsha")

    def test_date_boundary_next_day_sms_says_i_morgen(self):
        # Lead-funnet: kl. 22:22 må 05:04 neste driftsdøgn merkes «i morgen».
        fixed_now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        calls = [
            departure_call(start="2026-11-06T05:04:00+01:00", direction="Moss sentrum"),
            departure_call(start="2026-11-06T05:39:00+01:00", direction="Moss sentrum"),
        ]
        client = FakeEnturClient(
            departure_payload_fn=lambda stop_id, name: departure_payload(stop_id, name, calls=calls)
        )
        with tempfile.TemporaryDirectory() as tmp, RunningApp(
            tmp, client=client, now_fn=lambda: fixed_now
        ) as app:
            response = app.post_json(
                "/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"}
            )
        payload = response.json()
        self.assertEqual(response.status, 200)
        self.assertIn("i morgen: 05:04 mot Moss sentrum", payload["sms"]["text"])
        self.assertEqual(payload["sms"]["date_marks"], ["i morgen", "i morgen"])

    def test_requests_are_persisted_without_message(self):
        response = self.app.post_json(
            "/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"}
        )
        request_id = response.json()["request_id"]
        self.assertIsNotNone(request_id)
        rows = self.app.ctx.db.recent_requests(100)
        stored = [row for row in rows if row["id"] == request_id]
        self.assertEqual(len(stored), 1)
        self.assertNotIn("Skredderåsen", json.dumps(stored, ensure_ascii=False))
        self.assertEqual(stored[0]["message_hash"], "")


if __name__ == "__main__":
    unittest.main()
