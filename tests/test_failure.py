"""Feilhåndtering: Entur-feil, ugyldige svar og ærlige feilmeldinger."""

import tempfile
import unittest

from prototype.entur_client import EnturGraphQLError, EnturHTTPError, EnturTransportError
from tests.helpers import FakeEnturClient, RunningApp, departure_payload


class FailureModeTests(unittest.TestCase):
    def _simulate(self, client, message="Når går buss 22 fra Skredderåsen?"):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, client=client) as app:
            return app.post_json("/api/simulate", {"message": message})

    def test_entur_timeout_is_technical_error_not_500(self):
        response = self._simulate(FakeEnturClient(exception=EnturTransportError("timeout")))
        self.assertEqual(response.status, 200)
        payload = response.json()
        self.assertEqual(payload["result_type"], "TECHNICAL_ERROR")
        self.assertEqual(payload["error_category"], "EnturTransportError")
        self.assertNotIn("timeout", payload["sms"]["text"])
        self.assertIn("utilgjengelig", payload["sms"]["text"])

    def test_entur_http_error(self):
        response = self._simulate(FakeEnturClient(exception=EnturHTTPError(502, "bad gateway")))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()["result_type"], "TECHNICAL_ERROR")

    def test_graphql_error(self):
        response = self._simulate(
            FakeEnturClient(exception=EnturGraphQLError([{"message": "InvalidSyntax"}]))
        )
        self.assertEqual(response.json()["result_type"], "TECHNICAL_ERROR")

    def test_malformed_departure_payload_is_no_journey_not_crash(self):
        client = FakeEnturClient(
            departure_payload_fn=lambda stop_id, name: departure_payload(stop_id, name, calls=[])
        )
        response = self._simulate(client)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()["result_type"], "NO_JOURNEY")

    def test_unknown_place_is_honest_no_journey(self):
        response = self._simulate(
            FakeEnturClient(), message="Hvordan kommer jeg fra Tusenfryd til Refsnes?"
        )
        payload = response.json()
        self.assertEqual(payload["result_type"], "NO_JOURNEY")
        self.assertEqual(payload["result_reason"], "place_not_found")
        self.assertFalse(payload["recommended"])

    def test_technical_error_is_stored_and_visible_in_admin(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(
            tmp, client=FakeEnturClient(exception=EnturTransportError("nede"))
        ) as app:
            app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            rows = app.ctx.db.recent_errors(10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["error_category"], "EnturTransportError")
            self.assertEqual(rows[0]["status"], "error")
            # Ingen meldingstekst i feilraden
            import json

            self.assertNotIn("Skredderåsen", json.dumps(rows, ensure_ascii=False))
            self.assertEqual(app.ctx.db.get_counters().get("errors"), 1)

    def test_upstream_null_stop_place_is_technical_error(self):
        client = FakeEnturClient(departure_payload_fn=lambda stop_id, name: {"stopPlace": None})
        response = self._simulate(client)
        payload = response.json()
        self.assertEqual(payload["result_type"], "TECHNICAL_ERROR")
        self.assertEqual(payload["error_category"], "EnturNullData")


if __name__ == "__main__":
    unittest.main()
