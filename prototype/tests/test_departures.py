"""Enhetstester for avganger (estimatedCalls) og rutetid/sanntid-skille."""

import json
import unittest
from pathlib import Path

from prototype.departures import get_departures

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_departures_fixture():
    data = json.loads((FIXTURES / "live-departures-skredderasen-22.json").read_text(encoding="utf-8"))
    for capture in data["raw_captures"]:
        if capture["operation"] == "graphql" and "estimatedCalls" in capture["body"]:
            return json.loads(capture["body"])
    raise AssertionError("fant ikke departures-capture")


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.queries = []
        self.variables = []
        self.partial_errors = []

    def graphql(self, query, variables=None):
        self.queries.append(query)
        self.variables.append(variables)
        return self.payload


class DepartureTests(unittest.TestCase):
    def setUp(self):
        self.raw = load_departures_fixture()
        self.stop = self.raw["data"]["stopPlace"]

    def test_parses_departures_from_live_fixture(self):
        client = FakeClient(self.raw["data"])
        result = get_departures(client, "NSR:StopPlace:2636", number_of_departures=100, line_public_code="22")
        self.assertIsNotNone(result)
        self.assertEqual(result.stop_name, "Skredderåsen")
        self.assertGreater(len(result.departures), 0)
        self.assertEqual(result.line_filter, "22")
        first = result.departures[0]
        self.assertEqual(first.line_public_code, "22")
        self.assertEqual(first.line_id, "OST:Line:1_22")
        self.assertIn(first.direction, {"Kambo", "Moss sentrum"})
        self.assertIn("startTime", client.variables[0])
        self.assertEqual(client.variables[0]["stopPlaceId"], "NSR:StopPlace:2636")

    def test_timetable_only_flag(self):
        client = FakeClient(self.raw["data"])
        result = get_departures(client, "NSR:StopPlace:2636")
        # Live-capturen (2026-11-06 morgen) hadde realtime=false paa linje 22.
        self.assertTrue(result.timetable_only)
        self.assertTrue(all(d.is_timetable_only for d in result.departures))
        self.assertEqual(result.realtime_count, 0)
        self.assertEqual(result.departures[0].departure_time, result.departures[0].aimed)

    def test_realtime_departure_uses_expected_time(self):
        payload = {
            "stopPlace": {
                "id": "NSR:StopPlace:2900",
                "name": "Moss bussterminal",
                "transportMode": ["bus"],
                "quays": [],
                "estimatedCalls": [
                    {
                        "aimedDepartureTime": "2026-11-06T08:50:00+01:00",
                        "expectedDepartureTime": "2026-11-06T08:53:20+01:00",
                        "actualDepartureTime": None,
                        "realtime": True,
                        "predictionInaccurate": False,
                        "cancellation": False,
                        "quay": {"id": "q", "publicCode": "3", "name": "3"},
                        "destinationDisplay": {"frontText": "Refsnes"},
                        "serviceJourney": {
                            "id": "sj",
                            "directionType": "outbound",
                            "journeyPattern": {
                                "line": {"id": "OST:Line:1_20", "publicCode": "20", "name": "x", "transportMode": "bus"}
                            },
                        },
                        "situations": [],
                    }
                ],
            }
        }
        result = get_departures(FakeClient(payload), "NSR:StopPlace:2900")
        dep = result.departures[0]
        self.assertTrue(dep.realtime)
        self.assertEqual(dep.departure_time, "2026-11-06T08:53:20+01:00")
        self.assertEqual(dep.delay_seconds, 200)
        self.assertEqual(dep.quay_public_code, "3")

    def test_cancellation_and_situations_are_parsed(self):
        payload = {
            "stopPlace": {
                "id": "x", "name": "x", "transportMode": ["bus"], "quays": [],
                "estimatedCalls": [{
                    "aimedDepartureTime": "2026-11-06T08:00:00+01:00",
                    "expectedDepartureTime": "2026-11-06T08:00:00+01:00",
                    "actualDepartureTime": None, "realtime": False,
                    "predictionInaccurate": True, "cancellation": True,
                    "quay": {"id": "q", "publicCode": "", "name": ""},
                    "destinationDisplay": {"frontText": "Kambo"},
                    "serviceJourney": {"id": "sj", "directionType": "outbound",
                                       "journeyPattern": {"line": {"id": "l", "publicCode": "22", "name": "n", "transportMode": "bus"}}},
                    "situations": [{"id": "s", "severity": "warning",
                                    "summary": [{"value": "Forhåndsbestilling", "language": "nb"},
                                                {"value": "Booking", "language": "en"}]}],
                }],
            }
        }
        result = get_departures(FakeClient(payload), "x")
        dep = result.departures[0]
        self.assertTrue(dep.cancellation)
        self.assertTrue(dep.prediction_inaccurate)
        self.assertEqual(dep.situations, ["Forhåndsbestilling"])

    def test_unknown_stop_place_returns_none(self):
        result = get_departures(FakeClient({"stopPlace": None}), "NSR:StopPlace:999999")
        self.assertIsNone(result)

    def test_line_filter_that_matches_nothing(self):
        client = FakeClient(self.raw["data"])
        result = get_departures(client, "NSR:StopPlace:2636", line_public_code="540")
        self.assertEqual(result.departures, [])
        self.assertGreater(result.all_departures_count, 0)


if __name__ == "__main__":
    unittest.main()
