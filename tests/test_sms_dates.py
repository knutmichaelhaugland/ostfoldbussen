"""Dato-grense i SMS: neste driftsdøgn skal merkes «i morgen»."""

import unittest
from datetime import datetime

from app import sms_format
from prototype.departures import get_departures
from prototype.journeys import Assessment, parse_itineraries
from tests.helpers import (
    FakeEnturClient,
    departure_call,
    departure_payload,
    trip_payload,
    walk_trip_payload,
)


def stop_departures(calls, now):
    client = FakeEnturClient(
        departure_payload_fn=lambda stop_id, name: departure_payload(stop_id, name, calls=calls)
    )
    return get_departures(client, "NSR:StopPlace:2636")


def trip_itineraries(payload):
    return parse_itineraries(payload["trip"]["tripPatterns"])


class DateLabelTests(unittest.TestCase):
    def test_today_tomorrow_and_overmorgen(self):
        today = datetime.fromisoformat("2026-11-05T22:22:00+01:00").date()  # torsdag
        self.assertEqual(sms_format.date_label("2026-11-05T23:10:00+01:00", today), "i dag")
        self.assertEqual(sms_format.date_label("2026-11-06T05:04:00+01:00", today), "i morgen")
        self.assertEqual(sms_format.date_label("2026-11-07T05:04:00+01:00", today), "i overmorgen")
        self.assertEqual(sms_format.date_label("2026-11-10T05:04:00+01:00", today), "tir. 10. nov.")
        self.assertEqual(sms_format.date_label("2026-11-01T05:04:00+01:00", today), "søn. 1. nov.")

    def test_unknown_or_empty_gives_empty_label(self):
        today = datetime.fromisoformat("2026-11-05T22:22:00+01:00").date()
        self.assertEqual(sms_format.date_label(None, today), "")
        self.assertEqual(sms_format.date_label("tull", today), "")

    def test_utc_offset_is_normalized_to_oslo_day(self):
        # 2026-11-05T23:30Z = 2026-11-06 00:30 i Oslo -> «i morgen», ikke «i dag».
        today = datetime.fromisoformat("2026-11-05T22:22:00+01:00").date()
        tz = datetime.fromisoformat("2026-11-05T22:22:00+01:00").tzinfo
        self.assertEqual(
            sms_format.date_label("2026-11-05T23:30:00+00:00", today, tz=tz), "i morgen"
        )
        self.assertEqual(
            sms_format.date_label("2026-11-05T10:30:00+00:00", today, tz=tz), "i dag"
        )

    def test_cross_midnight_just_after_23_59_is_i_morgen(self):
        now = datetime.fromisoformat("2026-11-05T23:59:00+01:00")
        self.assertEqual(
            sms_format.date_label("2026-11-06T00:05:00+01:00", now.date()), "i morgen"
        )


class DepartureDateTests(unittest.TestCase):
    def test_next_day_departures_get_single_i_morgen_mark(self):
        now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        calls = [
            departure_call(start="2026-11-06T05:04:00+01:00", direction="Moss sentrum"),
            departure_call(start="2026-11-06T05:39:00+01:00", direction="Moss sentrum"),
            departure_call(start="2026-11-06T05:46:00+01:00", direction="Kambo"),
        ]
        text, marks = sms_format.format_departures_sms(stop_departures(calls, now), now)
        self.assertIn("i morgen: 05:04 mot Moss sentrum", text)
        self.assertEqual(text.count("i morgen"), 1)
        self.assertEqual(marks, ["i morgen", "i morgen", "i morgen"])
        self.assertIn("05:04", text)
        self.assertNotIn("i dag", text)

    def test_same_day_departures_get_i_dag_mark(self):
        now = datetime.fromisoformat("2026-11-06T08:00:00+01:00")
        calls = [
            departure_call(start="2026-11-06T08:39:00+01:00"),
            departure_call(start="2026-11-06T08:54:00+01:00", direction="Moss sentrum"),
        ]
        text, marks = sms_format.format_departures_sms(stop_departures(calls, now), now)
        self.assertIn("i dag: 08:39 mot Kambo", text)
        self.assertEqual(marks, ["i dag", "i dag"])
        self.assertNotIn("i morgen", text)

    def test_mixed_days_are_labelled_per_departure(self):
        now = datetime.fromisoformat("2026-11-05T23:50:00+01:00")
        calls = [
            departure_call(start="2026-11-05T23:55:00+01:00"),
            departure_call(start="2026-11-06T00:20:00+01:00", direction="Moss sentrum"),
            departure_call(start="2026-11-06T00:50:00+01:00"),
        ]
        text, marks = sms_format.format_departures_sms(stop_departures(calls, now), now)
        self.assertIn("i dag 23:55", text)
        self.assertIn("i morgen 00:20", text)
        self.assertIn("i morgen 00:50", text)
        self.assertEqual(marks, ["i dag", "i morgen", "i morgen"])

    def test_empty_departures_have_no_date_mark(self):
        now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        client = FakeEnturClient(
            departure_payload_fn=lambda stop_id, name: departure_payload(stop_id, name, calls=[])
        )
        stop = get_departures(client, "NSR:StopPlace:2636")
        text, marks = sms_format.format_departures_sms(stop, now)
        self.assertIn("ingen avganger", text)
        self.assertEqual(marks, [])

    def test_deterministic_and_gsm7_safe(self):
        now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        calls = [departure_call(start="2026-11-06T05:04:00+01:00")]
        stop = stop_departures(calls, now)
        first = sms_format.format_departures_sms(stop, now)
        second = sms_format.format_departures_sms(stop, now)
        self.assertEqual(first, second)
        from prototype import sms

        self.assertTrue(sms.count_segments(first[0]).gsm7_safe)


class TripDateTests(unittest.TestCase):
    def test_trip_tomorrow_gets_i_morgen_before_first_transit(self):
        now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        itinerary = trip_itineraries(trip_payload())[0]  # starter 2026-11-06T08:39
        text, mark = sms_format.format_trip_sms(itinerary, Assessment(), now)
        self.assertEqual(mark, "i morgen")
        self.assertIn("i morgen 08:39 linje 22", text)

    def test_trip_today_gets_i_dag(self):
        now = datetime.fromisoformat("2026-11-06T08:00:00+01:00")
        itinerary = trip_itineraries(trip_payload())[0]
        text, mark = sms_format.format_trip_sms(itinerary, Assessment(), now)
        self.assertEqual(mark, "i dag")
        self.assertIn("i dag 08:39 linje 22", text)

    def test_trip_with_leading_walk_marks_first_transit(self):
        now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        itinerary = trip_itineraries(walk_trip_payload(400.0))[0]
        text, mark = sms_format.format_trip_sms(itinerary, Assessment(), now)
        self.assertEqual(mark, "i morgen")
        self.assertIn("i morgen 08:39 linje 22", text)

    def test_trip_none_returns_empty(self):
        now = datetime.fromisoformat("2026-11-05T22:22:00+01:00")
        self.assertEqual(sms_format.format_trip_sms(None, None, now), ("", ""))


if __name__ == "__main__":
    unittest.main()
