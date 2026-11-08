"""Enhetstester for reisesøk, ettervalidering og scope-vakt.

Bruker en LIVE-CAPTURED fixture (prototype/tests/fixtures/, hentet fra Entur
2026-11-05 med ET-Client-Name: ostfoldbussen-selfhosted) + syntetiske varianter for
scope-brudd som ikke finnes i Østfold-data.
"""

import json
import unittest
from pathlib import Path

from prototype import config, journeys
from prototype.journeys import (
    Itinerary,
    Leg,
    ScopeReport,
    StopRef,
    TripSearchResult,
    parse_itineraries,
    build_transfers,
    check_scope,
    select_itinerary,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_raw_capture(filename, operation="graphql", contains=""):
    data = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    for capture in data["raw_captures"]:
        if capture["operation"] == operation and contains in capture["body"]:
            return json.loads(capture["body"])
    raise AssertionError(f"fant ikke capture {operation}/{contains} i {filename}")


def make_leg(mode="bus", line="22", start="2026-11-06T08:39:00+01:00",
             end="2026-11-06T08:48:00+01:00", from_name="Skredderåsen",
             to_name="Moss bussterminal", from_stop="NSR:StopPlace:2636",
             to_stop="NSR:StopPlace:2900", distance=0.0, duration=540, realtime=False):
    return Leg(
        mode=mode,
        transport_submode="localBus",
        duration_s=duration,
        distance_m=distance,
        realtime=realtime,
        aimed_start=start,
        expected_start=start,
        aimed_end=end,
        expected_end=end,
        line_id=f"OST:Line:1_{line}" if line else "",
        line_public_code=line,
        line_name="test",
        line_transport_mode="bus" if mode == "bus" else "",
        from_ref=StopRef(stop_place_id=from_stop, quay_id=None, name=from_name),
        to_ref=StopRef(stop_place_id=to_stop, quay_id=None, name=to_name),
    )


def make_itinerary(index, legs, duration=1440):
    return Itinerary(
        index=index,
        expected_start=legs[0].expected_start,
        expected_end=legs[-1].expected_end,
        aimed_start=legs[0].aimed_start,
        aimed_end=legs[-1].aimed_end,
        duration_s=duration,
        walk_time_s=0,
        waiting_time_s=0,
        distance_m=1000.0,
        street_distance_m=0.0,
        legs=legs,
    )


class FakeResolver:
    def __init__(self, counties):
        self.counties = counties
        self.calls = []

    def counties_of(self, ids):
        self.calls.append(list(ids))
        return {stop_id: self.counties.get(stop_id) for stop_id in ids}


class FakeGraphQLClient:
    def __init__(self, payload):
        self.payload = payload
        self.queries = []
        self.variables = []
        self.partial_errors = []

    def graphql(self, query, variables=None):
        self.queries.append(query)
        self.variables.append(variables)
        return self.payload


class ParseLiveFixtureTests(unittest.TestCase):
    def setUp(self):
        self.raw = load_raw_capture(
            "live-trip-skredderasen-refsnes.json", contains="tripPatterns"
        )
        self.patterns = self.raw["data"]["trip"]["tripPatterns"]

    def test_parses_four_patterns(self):
        itineraries = parse_itineraries(self.patterns)
        self.assertEqual(len(itineraries), 4)
        first = itineraries[0]
        self.assertEqual(first.expected_start, "2026-11-06T08:39:00+01:00")
        self.assertEqual(first.expected_end, "2026-11-06T09:03:00+01:00")
        self.assertEqual(len(first.transit_legs), 2)
        self.assertEqual(first.transit_legs[0].line_public_code, "22")
        self.assertEqual(first.transit_legs[1].line_public_code, "20")
        self.assertEqual(first.transit_legs[0].to_ref.stop_place_id, "NSR:StopPlace:2900")

    def test_transfer_is_120_seconds_in_fixture(self):
        itineraries = parse_itineraries(self.patterns)
        transfers = build_transfers(itineraries[0], minimum_s=120, warn_below_s=300)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0].slack_s, 120)
        self.assertFalse(transfers[0].is_short)
        self.assertTrue(transfers[0].is_warn_only)

    def test_assessment_with_api_default_minimum_is_suitable(self):
        thresholds = config.Thresholds(transfer_slack_s=120, minimum_transfer_s=120)
        itineraries = parse_itineraries(self.patterns)
        resolver = FakeResolver(
            {
                "NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
                "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
                "NSR:StopPlace:3029": config.OSTFOLD_COUNTY_ID,
            }
        )
        assessment = journeys.assess_itinerary(itineraries[0], thresholds, resolver)
        self.assertEqual(assessment.classification, "EGNET")
        self.assertEqual(assessment.scope.status, "OK")
        self.assertEqual(assessment.walk_total_m, 0.0)

    def test_postcheck_catches_short_transfer_when_minimum_is_higher(self):
        thresholds = config.Thresholds(transfer_slack_s=120, minimum_transfer_s=300)
        itineraries = parse_itineraries(self.patterns)
        resolver = FakeResolver(
            {
                "NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
                "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
                "NSR:StopPlace:3029": config.OSTFOLD_COUNTY_ID,
            }
        )
        assessment = journeys.assess_itinerary(itineraries[0], thresholds, resolver)
        self.assertEqual(assessment.classification, "UEGNET")
        self.assertTrue(any(v.startswith("KORT_BYTTE") for v in assessment.violations))


class WalkAndSelectionTests(unittest.TestCase):
    def test_walk_limit_is_enforced_post_hoc(self):
        legs = [
            make_leg(mode="foot", line="", start="2026-11-06T08:00:00+01:00",
                     end="2026-11-06T08:15:00+01:00", from_name="Hjemme",
                     to_name="Skredderåsen", distance=800.0, duration=900),
            make_leg(),
        ]
        itinerary = make_itinerary(0, legs)
        thresholds = config.Thresholds(max_walk_m=500.0)
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID}
        )
        assessment = journeys.assess_itinerary(itinerary, thresholds, resolver)
        self.assertEqual(assessment.walk_total_m, 800.0)
        self.assertIn("MYE_GANGE:800m>500m", assessment.violations)
        self.assertEqual(assessment.classification, "UEGNET")

    def test_leg_walk_limit(self):
        legs = [
            make_leg(mode="foot", line="", distance=300.0, duration=300),
            make_leg(),
        ]
        itinerary = make_itinerary(0, legs)
        thresholds = config.Thresholds(max_walk_leg_m=250.0)
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID}
        )
        assessment = journeys.assess_itinerary(itinerary, thresholds, resolver)
        self.assertTrue(any(v.startswith("MYE_GANGE_BEIN") for v in assessment.violations))

    def test_walk_time_limit(self):
        legs = [
            make_leg(mode="foot", line="", distance=100.0, duration=1200),
            make_leg(),
        ]
        itinerary = make_itinerary(0, legs)
        thresholds = config.Thresholds(max_walk_time_s=600)
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID}
        )
        assessment = journeys.assess_itinerary(itinerary, thresholds, resolver)
        self.assertTrue(any(v.startswith("MYE_GANGTID") for v in assessment.violations))

    def test_selection_prefers_suitable_without_scope_flag(self):
        good_legs = [make_leg()]
        flagged_legs = [make_leg(to_stop="NSR:StopPlace:337", to_name="Oslo S")]
        itineraries = [make_itinerary(0, flagged_legs), make_itinerary(1, good_legs)]
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:337": "KVE:TopographicPlace:03"}
        )
        thresholds = config.Thresholds()
        assessments = journeys.assess_all(itineraries, thresholds, resolver)
        # Itinerary 0 ender i Oslo S = maal (ikke mellombytte) -> ikke flagget.
        # Bygg heller en reise med Oslo S som mellombytte:
        legs = [
            make_leg(),
            make_leg(start="2026-11-06T08:50:00+01:00", end="2026-11-06T09:10:00+01:00",
                     line="20", from_name="Moss bussterminal", to_name="Oslo S",
                     from_stop="NSR:StopPlace:2900", to_stop="NSR:StopPlace:337"),
            make_leg(start="2026-11-06T09:20:00+01:00", end="2026-11-06T09:40:00+01:00",
                     line="21", from_name="Oslo S", to_name="Refsnes",
                     from_stop="NSR:StopPlace:337", to_stop="NSR:StopPlace:3029"),
        ]
        flagged_it = make_itinerary(0, legs)
        good_it = make_itinerary(1, [make_leg()])
        itineraries = [flagged_it, good_it]
        assessments = journeys.assess_all(itineraries, thresholds, resolver)
        self.assertEqual(assessments[0].scope.status, "FLAGG")
        self.assertEqual(assessments[1].scope.status, "OK")
        selection = select_itinerary(itineraries, assessments)
        self.assertEqual(selection.itinerary.index, 1)
        self.assertEqual(selection.reason, "egnet")

    def test_selection_falls_back_to_flagged_when_only_option(self):
        legs = [
            make_leg(),
            make_leg(start="2026-11-06T08:50:00+01:00", end="2026-11-06T09:10:00+01:00",
                     line="20", from_name="Moss bussterminal", to_name="Oslo S",
                     from_stop="NSR:StopPlace:2900", to_stop="NSR:StopPlace:337"),
            make_leg(start="2026-11-06T09:20:00+01:00", end="2026-11-06T09:40:00+01:00",
                     line="21", from_name="Oslo S", to_name="Refsnes",
                     from_stop="NSR:StopPlace:337", to_stop="NSR:StopPlace:3029"),
        ]
        itinerary = make_itinerary(0, legs)
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:337": "KVE:TopographicPlace:03",
             "NSR:StopPlace:3029": config.OSTFOLD_COUNTY_ID}
        )
        assessments = journeys.assess_all([itinerary], config.Thresholds(), resolver)
        selection = select_itinerary([itinerary], assessments)
        self.assertEqual(selection.reason, "egnet, men scope-vakt flagget")

    def test_selection_with_no_itineraries(self):
        selection = select_itinerary([], {})
        self.assertIsNone(selection.itinerary)
        self.assertEqual(selection.reason, "ingen forslag")


class ScopeGuardTests(unittest.TestCase):
    def test_intermediate_outside_ostfold_is_flagged_not_hidden(self):
        legs = [
            make_leg(),
            make_leg(start="2026-11-06T08:50:00+01:00", end="2026-11-06T09:10:00+01:00",
                     line="20", from_name="Moss bussterminal", to_name="Oslo S",
                     from_stop="NSR:StopPlace:2900", to_stop="NSR:StopPlace:337"),
            make_leg(start="2026-11-06T09:20:00+01:00", end="2026-11-06T09:40:00+01:00",
                     line="21", from_name="Oslo S", to_name="Refsnes",
                     from_stop="NSR:StopPlace:337", to_stop="NSR:StopPlace:3029"),
        ]
        itinerary = make_itinerary(0, legs)
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:337": "KVE:TopographicPlace:03",
             "NSR:StopPlace:3029": config.OSTFOLD_COUNTY_ID}
        )
        report = check_scope(itinerary, resolver)
        self.assertEqual(report.status, "FLAGG")
        self.assertEqual(len(report.outside), 1)
        self.assertEqual(report.outside[0]["stop_place_id"], "NSR:StopPlace:337")
        self.assertEqual(report.outside[0]["county_id"], "KVE:TopographicPlace:03")
        # Reisen skjules ikke: alle transit-stopp er fortsatt med i rapporten.
        self.assertIn("NSR:StopPlace:337", report.transit_stop_ids)

    def test_start_and_goal_are_exempt(self):
        legs = [
            make_leg(from_stop="NSR:StopPlace:337", from_name="Oslo S"),
            make_leg(start="2026-11-06T08:50:00+01:00", end="2026-11-06T09:03:00+01:00",
                     line="20", from_name="Moss bussterminal", to_name="Refsnes",
                     from_stop="NSR:StopPlace:2900", to_stop="NSR:StopPlace:3029"),
        ]
        itinerary = make_itinerary(0, legs)
        resolver = FakeResolver(
            {"NSR:StopPlace:337": "KVE:TopographicPlace:03",
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:3029": config.OSTFOLD_COUNTY_ID}
        )
        report = check_scope(itinerary, resolver)
        self.assertEqual(report.status, "OK")

    def test_geocoder_failure_is_unknown_not_hidden(self):
        itinerary = make_itinerary(0, [make_leg()])
        report = check_scope(itinerary, None)
        self.assertEqual(report.status, "UKJENT")
        self.assertTrue(report.flagged)

    def test_geocoder_exception_is_unknown(self):
        class ExplodingResolver:
            def counties_of(self, ids):
                raise RuntimeError("nede")

        report = check_scope(make_itinerary(0, [make_leg()]), ExplodingResolver())
        self.assertEqual(report.status, "UKJENT")
        self.assertIn("geocoder-feil", report.error)


class SearchTripsTests(unittest.TestCase):
    def setUp(self):
        self.raw = load_raw_capture(
            "live-trip-skredderasen-refsnes.json", contains="tripPatterns"
        )

    def test_search_trips_parses_and_assesses(self):
        client = FakeGraphQLClient(self.raw["data"])
        resolver = FakeResolver(
            {"NSR:StopPlace:2636": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:2900": config.OSTFOLD_COUNTY_ID,
             "NSR:StopPlace:3029": config.OSTFOLD_COUNTY_ID}
        )
        thresholds = config.Thresholds(transfer_slack_s=120, minimum_transfer_s=120)
        result = journeys.search_trips(
            client, "NSR:StopPlace:2636", "NSR:StopPlace:3029",
            "2026-11-06T08:30:00+01:00", thresholds=thresholds, resolver=resolver,
        )
        self.assertEqual(result.status, "OK")
        self.assertEqual(len(result.itineraries), 4)
        self.assertEqual(client.variables[0]["transferSlack"], 120)
        self.assertEqual(client.variables[0]["numTripPatterns"], 10)
        self.assertEqual(result.assessments[0].classification, "EGNET")

    def test_transfer_slack_is_configurable(self):
        client = FakeGraphQLClient(self.raw["data"])
        thresholds = config.Thresholds(transfer_slack_s=600, minimum_transfer_s=600)
        journeys.search_trips(
            client, "NSR:StopPlace:2636", "NSR:StopPlace:3029",
            "2026-11-06T08:30:00+01:00", thresholds=thresholds,
            resolver=FakeResolver({}),
        )
        self.assertEqual(client.variables[0]["transferSlack"], 600)
        self.assertNotIn("searchWindow", client.variables[0])

    def test_routing_errors_gives_status(self):
        client = FakeGraphQLClient(
            {"trip": {"tripPatterns": [], "routingErrors": [{"code": "locationNotFound", "description": "x"}]}}
        )
        result = journeys.search_trips(
            client, "NSR:StopPlace:999999", "NSR:StopPlace:3029",
            "2026-11-06T08:30:00+01:00", resolver=FakeResolver({}),
        )
        self.assertEqual(result.status, "RUTING_FEIL")
        self.assertEqual(result.routing_errors[0]["code"], "locationNotFound")

    def test_null_trip_gives_no_patterns(self):
        client = FakeGraphQLClient({"trip": None})
        result = journeys.search_trips(
            client, "NSR:StopPlace:2636", "NSR:StopPlace:3029",
            "2026-11-06T08:30:00+01:00", resolver=FakeResolver({}),
        )
        self.assertEqual(result.status, "INGEN_FORSLAG")
        self.assertFalse(result.has_patterns)


if __name__ == "__main__":
    unittest.main()
