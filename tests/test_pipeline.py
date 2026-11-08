"""Kontraktstester for pipeline med fake Entur-data (ingen nettverk).

Dekker resultattyper, scope (scope), feilhåndtering (feil), realtime (realtime),
overgang (overgang), gange (gange).
"""

import json
import tempfile
import unittest

from app.pipeline import Pipeline, PipelineDeps
from prototype.entur_client import EnturGraphQLError, EnturTransportError
from prototype.geocoder import PlaceResolver
from tests.helpers import (
    FakeEnturClient,
    departure_call,
    departure_payload,
    fake_probe_factory,
    make_config,
    scope_trip_payload,
    trip_payload,
    walk_trip_payload,
)
from app.db import Database


def build_pipeline(tmpdir, config_overrides=None, client=None, now_fn=None):
    config = make_config(tmpdir, **(config_overrides or {}))
    client = client or FakeEnturClient()
    db = Database(config.database_path)
    db.init()
    pipeline = Pipeline(
        config,
        db,
        deps=PipelineDeps(client=client, resolver=PlaceResolver(client), thresholds=config.thresholds()),
        now_fn=now_fn,
    )
    return pipeline, db, config, client


class DeparturePipelineTests(unittest.TestCase):
    def test_departures_valid_suitable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, db, _, _ = build_pipeline(tmp)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(trace["result_type"], "VALID_SUITABLE")
            self.assertTrue(trace["recommended"])
            self.assertEqual(trace["intent"]["kind"], "DEPARTURES")
            self.assertEqual(trace["places"]["from"]["id"], "NSR:StopPlace:2636")
            self.assertEqual(trace["departures"][0]["line"], "22")
            self.assertTrue(trace["departures"][0]["timetable_only"])
            self.assertIn("Rutetider", trace["sms"]["text"])
            self.assertEqual(trace["sms"]["segments"]["encoding"], "GSM-7")
            self.assertGreaterEqual(trace["latency_ms"], 0)
            self.assertIsNotNone(trace["request_id"])
            self.assertEqual(db.request_counts()["total"], 1)

    def test_no_departures_is_no_journey(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(
                departure_payload_fn=lambda stop_id, name: departure_payload(
                    stop_id, name, calls=[]
                )
            )
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(trace["result_type"], "NO_JOURNEY")
            self.assertEqual(trace["result_reason"], "no_departures")
            self.assertFalse(trace["recommended"])

    def test_unknown_stop_place_null_is_technical_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(
                departure_payload_fn=lambda stop_id, name: {"stopPlace": None}
            )
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(trace["result_type"], "TECHNICAL_ERROR")
            self.assertEqual(trace["error_category"], "EnturNullData")

    def test_cancelled_departures_are_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [departure_call(cancellation=True)]
            client = FakeEnturClient(
                departure_payload_fn=lambda stop_id, name: departure_payload(
                    stop_id, name, calls=calls
                )
            )
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(trace["result_type"], "NO_JOURNEY")
            self.assertEqual(trace["result_reason"], "all_cancelled")
            self.assertTrue(trace["departures"][0]["cancellation"])

    def test_realtime_true_without_delay_is_not_delayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                departure_call(
                    start="2026-11-06T08:39:00+01:00",
                    expected="2026-11-06T08:39:00+01:00",
                    realtime=True,
                )
            ]
            client = FakeEnturClient(
                departure_payload_fn=lambda stop_id, name: departure_payload(
                    stop_id, name, calls=calls
                )
            )
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            departure = trace["departures"][0]
            self.assertTrue(departure["realtime"])
            self.assertEqual(departure["delay_s"], 0)
            self.assertNotIn("Rutetider", trace["sms"]["text"])
            self.assertIn("Sanntid", trace["sms"]["text"])

    def test_realtime_delay_uses_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = [
                departure_call(
                    start="2026-11-06T08:50:00+01:00",
                    expected="2026-11-06T08:53:20+01:00",
                    realtime=True,
                )
            ]
            client = FakeEnturClient(
                departure_payload_fn=lambda stop_id, name: departure_payload(
                    stop_id, name, calls=calls
                )
            )
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            departure = trace["departures"][0]
            self.assertEqual(departure["delay_s"], 200)
            self.assertEqual(departure["display_time"], "2026-11-06T08:53:20+01:00")


class TripPipelineTests(unittest.TestCase):
    def test_suitable_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _ = build_pipeline(tmp)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "VALID_SUITABLE")
            self.assertTrue(trace["recommended"])
            self.assertEqual(trace["selected"]["index"], 0)
            self.assertEqual(trace["places"]["to"]["id"], "NSR:StopPlace:3029")
            self.assertEqual(trace["itineraries"][0]["transfers"][0]["slack_s"], 120)
            self.assertIn("Moss bussterminal", trace["sms"]["text"])
            self.assertEqual(trace["sms"]["segments"]["encoding"], "GSM-7")

    def test_short_transfer_makes_unsuitable_and_never_recommended(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _ = build_pipeline(tmp, {"minimum_transfer_s": 300, "transfer_slack_s": 120})
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "VALID_UNSUITABLE")
            self.assertFalse(trace["recommended"])
            self.assertFalse(trace["selected"]["recommended"])
            self.assertIn("IKKE anbefalt", trace["sms"]["text"])
            self.assertTrue(any("kort bytte" in warning for warning in trace["warnings"]))

    def test_walk_limit_makes_unsuitable(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(trip_payload=walk_trip_payload(800.0))
            pipeline, _, _, _ = build_pipeline(tmp, {"max_walk_m": 500}, client=client)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "VALID_UNSUITABLE")
            self.assertTrue(any("MYE_GANGE" in violation for violation in trace["itineraries"][0]["violations"]))
            self.assertFalse(trace["recommended"])

    def test_scope_breach_is_flagged_and_unsuitable(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(trip_payload=scope_trip_payload())
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Hvordan kommer jeg fra Moss stasjon til Mysen?")
            self.assertEqual(trace["result_type"], "VALID_UNSUITABLE")
            self.assertFalse(trace["recommended"])
            self.assertEqual(trace["itineraries"][0]["scope"]["status"], "FLAGG")
            self.assertTrue(
                any("forlater Østfold" in warning for warning in trace["warnings"]),
                trace["warnings"],
            )

    def test_require_in_scope_rejects_cross_border(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(trip_payload=scope_trip_payload())
            pipeline, _, _, _ = build_pipeline(
                tmp, {"scope_policy": "require_in_scope"}, client=client
            )
            trace = pipeline.run("Hvordan kommer jeg fra Moss stasjon til Mysen?")
            self.assertEqual(trace["result_type"], "NO_JOURNEY")
            self.assertEqual(trace["result_reason"], "scope_rejected")
            self.assertFalse(trace["recommended"])

    def test_routing_error_is_no_journey(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _ = build_pipeline(tmp)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "VALID_SUITABLE")
            # Ukjent sted -> NO_JOURNEY (ikke teknisk feil)
            trace = pipeline.run("Hvordan kommer jeg fra Oslo S til Refsnes?")
            self.assertEqual(trace["result_type"], "NO_JOURNEY")
            self.assertEqual(trace["result_reason"], "place_not_found")

    def test_no_patterns_is_no_journey(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(trip_payload={"trip": {"tripPatterns": [], "routingErrors": []}})
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "NO_JOURNEY")
            self.assertEqual(trace["result_reason"], "no_journey")

    def test_entur_exception_is_technical_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(exception=EnturTransportError("timeout"))
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "TECHNICAL_ERROR")
            self.assertEqual(trace["error_category"], "EnturTransportError")
            self.assertNotIn("timeout", trace["sms"]["text"])

    def test_graphql_partial_error_client_never_returns_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(exception=EnturGraphQLError([{"message": "boom"}]))
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(trace["result_type"], "TECHNICAL_ERROR")

    def test_unknown_intent_is_no_journey(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, _ = build_pipeline(tmp)
            trace = pipeline.run("Hva er været i Moss?")
            self.assertEqual(trace["result_type"], "NO_JOURNEY")
            self.assertEqual(trace["result_reason"], "intent_not_understood")
            self.assertIn("forstod ikke", trace["warnings"][0])

    def test_conversation_context_is_used_and_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, db, _, _ = build_pipeline(tmp)
            first = pipeline.run(
                "Hvordan kommer jeg fra Skredderåsen til Refsnes?",
                conversation_key="conv-1",
            )
            self.assertEqual(first["result_type"], "VALID_SUITABLE")
            second = pipeline.run("Når går bussen?", conversation_key="conv-1")
            self.assertEqual(second["intent"]["kind"], "DEPARTURES")
            self.assertEqual(second["places"]["from"]["id"], "NSR:StopPlace:2636")
            self.assertEqual(second["interpretation_source"], "context")

    def test_no_raw_message_or_phone_in_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, db, _, _ = build_pipeline(tmp)
            message = "Hvordan kommer jeg fra Skredderåsen til Refsnes? 98765432"
            trace = pipeline.run(message, pseudonym="p" * 64, channel="sms")
            rows = db.recent_requests(10)
            serialized = json.dumps(rows, ensure_ascii=False)
            self.assertNotIn("98765432", serialized)
            self.assertNotIn("Skredderåsen", serialized)
            from app.pipeline import message_hash

            self.assertEqual(rows[0]["message_hash"], "")
            self.assertEqual(message_hash(message), "")


class ThresholdConfigTests(unittest.TestCase):
    def test_transfer_slack_is_sent_to_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, _, _, client = build_pipeline(tmp, {"transfer_slack_s": 480})
            pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            trip_requests = [
                request for request in client.requests if "query" in request and "tripPatterns" in request["query"]
            ]
            self.assertEqual(trip_requests[0]["variables"]["transferSlack"], 480)


if __name__ == "__main__":
    unittest.main()


class PartialGraphQLErrorTests(unittest.TestCase):
    def test_partial_departures_are_not_presented_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient()
            client.partial_errors = [{"message": "partial departure field"}]
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Når går buss 22 fra Skredderåsen?")
            self.assertEqual(trace["result_type"], "TECHNICAL_ERROR")
            self.assertEqual(trace["result_reason"], "partial_graphql_errors")
            self.assertNotEqual(trace["sms"]["text"], "")

    def test_partial_trip_search_is_not_presented_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient()
            client.partial_errors = [{"message": "partial trip field"}]
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertEqual(trace["result_type"], "TECHNICAL_ERROR")
            self.assertEqual(trace["result_reason"], "partial_graphql_errors")


class MissingTransferTimeTests(unittest.TestCase):
    def test_missing_transfer_time_is_never_recommended(self):
        import copy
        from tests.helpers import trip_payload
        payload = copy.deepcopy(trip_payload())
        first = payload["trip"]["tripPatterns"][0]["legs"][0]
        first["expectedEndTime"] = ""
        first["aimedEndTime"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeEnturClient(trip_payload=payload)
            pipeline, _, _, _ = build_pipeline(tmp, client=client)
            trace = pipeline.run("Hvordan kommer jeg fra Skredderåsen til Refsnes?")
            self.assertFalse(trace["recommended"])
            self.assertIn(trace["result_type"], {"VALID_UNSUITABLE", "NO_JOURNEY"})
