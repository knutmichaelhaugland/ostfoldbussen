"""Feilgjennomgangskø (mandat §10): felter, skriving, admin-oppdatering."""

import tempfile
import unittest

from prototype.entur_client import EnturTransportError
from tests.helpers import FakeEnturClient, RunningApp, invite, make_config


class ErrorReviewDbTests(unittest.TestCase):
    def test_add_recent_update_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = invite(tmp + "/app.db")
            review_id = db.add_error_review(
                created_at="2026-11-05T21:00:00+00:00",
                request_id=7,
                category="EnturTransportError",
                pseudonym_ref="p_123",
                place_ids=["NSR:StopPlace:2636"],
                failure_stage="entur",
                build_sha="abc123",
                suggested_correction="prøv igjen / sjekk Entur-status",
                regression_ref="tests/test_failure.py::test_entur_timeout",
            )
            rows = db.recent_error_reviews(10)
            self.assertEqual(len(rows), 1)
            first = rows[0]
            self.assertEqual(first["id"], review_id)
            self.assertEqual(first["review_status"], "OPEN")
            self.assertEqual(first["place_ids"], ["NSR:StopPlace:2636"])
            self.assertEqual(first["failure_stage"], "entur")
            self.assertTrue(db.update_error_review(review_id, "REVIEWED", "sett på"))
            self.assertEqual(db.recent_error_reviews(1)[0]["review_status"], "REVIEWED")
            self.assertEqual(db.error_review_counts()["REVIEWED"], 1)
            with self.assertRaises(ValueError):
                db.update_error_review(review_id, "UGYLDIG")


class ErrorReviewPipelineTests(unittest.TestCase):
    def test_technical_error_is_queued(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(
            tmp, client=FakeEnturClient(exception=EnturTransportError("nede"))
        ) as app:
            app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            rows = app.ctx.db.recent_error_reviews(10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["failure_stage"], "entur")
            self.assertEqual(rows[0]["category"], "EnturTransportError")
            self.assertEqual(rows[0]["build_sha"], "testsha")

    def test_unknown_place_is_queued_as_geocoding(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            app.post_json("/api/simulate", {"message": "Når går bussen fra Ukjentplass?"})
            rows = app.ctx.db.recent_error_reviews(10)
            self.assertTrue(rows)
            self.assertEqual(rows[0]["failure_stage"], "geocoding")

    def test_success_does_not_queue(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            self.assertEqual(app.ctx.db.recent_error_reviews(10), [])


class ErrorReviewAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = RunningApp(self.tmp.name)
        self.app.__enter__()

    def tearDown(self):
        self.app.__exit__()
        self.tmp.cleanup()

    def test_admin_errors_requires_auth(self):
        response = self.app.get("/admin/errors")
        self.assertEqual(response.status, 401)

    def test_admin_can_update_review(self):
        review_id = self.app.ctx.db.add_error_review(
            created_at="2026-11-05T21:00:00+00:00",
            request_id=1,
            category="EnturTransportError",
            pseudonym_ref="p_x",
            place_ids=[],
            failure_stage="entur",
            build_sha="testsha",
        )
        login_response, cookies = self.app.login()
        self.assertEqual(login_response.status, 303)
        page = self.app.get("/admin/errors", cookies=cookies)
        self.assertEqual(page.status, 200)
        self.assertIn("Feilgjennomgang", page.text)
        marker = 'name="csrf" value="'
        start = page.text.find(marker)
        self.assertGreaterEqual(start, 0)
        csrf = page.text[start + len(marker):].split('"')[0]
        response = self.app.post_form(
            "/admin/errors",
            {"csrf": csrf, "id": str(review_id), "status": "FIXED", "note": "rettet"},
            cookies=cookies,
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(self.app.ctx.db.recent_error_reviews(1)[0]["review_status"], "FIXED")
