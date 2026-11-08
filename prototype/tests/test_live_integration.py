"""Live-integrasjonstester mot Entur. Hoppes over med mindre RUN_LIVE=1.

Kjør: RUN_LIVE=1 python3 -m unittest prototype.tests.test_live_integration -v
"""

import os
import unittest

from prototype import config, geocoder, journeys
from prototype.departures import get_departures
from prototype.entur_client import EnturClient, EnturGraphQLError

RUN_LIVE = os.environ.get("RUN_LIVE") == "1"


@unittest.skipUnless(RUN_LIVE, "sett RUN_LIVE=1 for aa kjore live-integrasjonstester")
class LiveEnturTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = EnturClient()
        cls.resolver = geocoder.PlaceResolver(cls.client)

    def test_01_geocoder_skredderasen(self):
        res = self.resolver.resolve("Skredderåsen")
        self.assertTrue(res.found)
        self.assertEqual(res.hit.id, "NSR:StopPlace:2636")
        self.assertEqual(res.hit.county_id, config.OSTFOLD_COUNTY_ID)
        self.assertEqual(res.hit.layer, "stopPlace")

    def test_02_geocoder_counties_filter_excludes_oslo(self):
        params = {
            "q": "Oslo S",
            "counties": config.OSTFOLD_COUNTY_ID,
            "layers": "stopPlace",
            "limit": "5",
        }
        payload = self.client.geocoder_autocomplete(params)
        for feature in payload.get("features") or []:
            props = feature["properties"]
            self.assertEqual(props["layer"], "stopPlace")
            self.assertEqual(props["address"]["countyId"], config.OSTFOLD_COUNTY_ID)

    def test_03_alias_moss_sentrum(self):
        res = self.resolver.resolve("Moss sentrum")
        self.assertTrue(res.found)
        self.assertTrue(res.alias_used)
        self.assertEqual(res.hit.id, "NSR:StopPlace:2900")

    def test_04_unknown_stop_place_returns_none(self):
        self.assertIsNone(get_departures(self.client, "NSR:StopPlace:999999999"))

    def test_05_departures_skredderasen(self):
        result = get_departures(
            self.client, "NSR:StopPlace:2636", number_of_departures=20, line_public_code="22"
        )
        self.assertIsNotNone(result)
        self.assertGreater(len(result.departures), 0)
        for departure in result.departures:
            self.assertEqual(departure.line_public_code, "22")
            self.assertIsInstance(departure.realtime, bool)
        # Skredderåsen/linje 22 har ofte realtime=false; skal da merkes som rutetid.
        if result.timetable_only:
            self.assertTrue(all(d.is_timetable_only for d in result.departures))

    def test_06_trip_skredderasen_refsnes(self):
        thresholds = config.Thresholds(transfer_slack_s=300, minimum_transfer_s=300)
        result = journeys.search_trips(
            self.client,
            "NSR:StopPlace:2636",
            "NSR:StopPlace:3029",
            "2026-11-06T08:30:00+01:00",
            thresholds=thresholds,
            resolver=self.resolver,
        )
        self.assertEqual(result.status, "OK")
        self.assertGreater(len(result.itineraries), 0)
        for itinerary in result.itineraries:
            assessment = result.assessments[itinerary.index]
            # API-et skal ha håndhevet transferSlack=300 hardt.
            for transfer in assessment.transfers:
                self.assertGreaterEqual(transfer.slack_s, 300)
            self.assertIn(assessment.scope.status, {"OK", "FLAGG", "UKJENT"})

    def test_07_scope_guard_marks_ostfold_stops(self):
        counties = self.resolver.counties_of(
            ["NSR:StopPlace:2636", "NSR:StopPlace:2900", "NSR:StopPlace:3029"]
        )
        for stop_id, county in counties.items():
            self.assertEqual(county, config.OSTFOLD_COUNTY_ID, stop_id)

    def test_08_partial_error_form_is_surfaced(self):
        # Ugyldig GraphQL skal gi GraphQL-errors (HTTP 200), aldri stille data.
        with self.assertRaises(EnturGraphQLError):
            self.client.graphql("{ stopPlace(id: }")


if __name__ == "__main__":
    unittest.main()
