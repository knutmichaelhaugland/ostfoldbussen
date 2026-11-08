"""Enhetstester for deterministisk norsk formatering og SMS-utkast."""

import unittest
from datetime import datetime

from prototype import formatting, sms
from prototype.departures import Departure, StopDepartures
from prototype.journeys import Assessment, Itinerary, Leg, ScopeReport, StopRef, Transfer


def make_departure(**overrides):
    defaults = dict(
        line_public_code="22",
        line_id="OST:Line:1_22",
        line_name="Skredderåsen-Kambo",
        transport_mode="bus",
        direction="Kambo",
        direction_type="outbound",
        aimed="2026-11-06T08:39:00+01:00",
        expected="2026-11-06T08:39:00+01:00",
        actual=None,
        realtime=False,
        prediction_inaccurate=False,
        cancellation=False,
        quay_id="NSR:Quay:4602",
        quay_public_code="",
    )
    defaults.update(overrides)
    return Departure(**defaults)


def make_stop(departures, line_filter="22"):
    return StopDepartures(
        stop_place_id="NSR:StopPlace:2636",
        stop_name="Skredderåsen",
        transport_modes=["bus"],
        quays=[],
        departures=departures,
        line_filter=line_filter,
        all_departures_count=len(departures),
    )


def make_leg(mode="bus", start="2026-11-06T08:39:00+01:00", end="2026-11-06T08:48:00+01:00",
             line="22", from_name="Skredderåsen", to_name="Moss bussterminal",
             from_stop="NSR:StopPlace:2636", to_stop="NSR:StopPlace:2900",
             distance=0.0, duration=540, realtime=False):
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
        line_id=f"OST:Line:1_{line}",
        line_public_code=line,
        line_name="test",
        line_transport_mode="bus" if mode == "bus" else "",
        from_ref=StopRef(stop_place_id=from_stop, quay_id=None, name=from_name),
        to_ref=StopRef(stop_place_id=to_stop, quay_id=None, name=to_name),
    )


def make_itinerary(legs):
    return Itinerary(
        index=0,
        expected_start=legs[0].expected_start,
        expected_end=legs[-1].expected_end,
        aimed_start=legs[0].aimed_start,
        aimed_end=legs[-1].aimed_end,
        duration_s=1440,
        walk_time_s=0,
        waiting_time_s=120,
        distance_m=9327.0,
        street_distance_m=0.0,
        legs=legs,
    )


class ClockAndDateTests(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(formatting.format_clock("2026-11-06T08:39:00+01:00"), "08:39")
        self.assertEqual(formatting.format_clock(None), "?")
        self.assertEqual(formatting.format_clock("rart"), "rart")

    def test_date_is_deterministic_norwegian(self):
        self.assertEqual(formatting.format_date_no("2026-11-06T08:39:00+01:00"), "fre. 6. nov. 2026")
        self.assertEqual(formatting.format_date_no("2026-11-08T08:39:00+01:00"), "søn. 8. nov. 2026")

    def test_minutes(self):
        self.assertEqual(formatting.format_minutes(120), "2 min")
        self.assertEqual(formatting.format_minutes(-5), "0 min")


class GsmSanitizeTests(unittest.TestCase):
    def test_dash_and_quotes_become_gsm7(self):
        text = formatting.to_gsm7_text("Buss 22 – «Moss sentrum» · Refsnes…")
        self.assertTrue(sms.is_gsm7_safe(text))
        self.assertIn("Buss 22 -", text)
        self.assertIn('"Moss sentrum"', text)

    def test_norwegian_letters_preserved(self):
        self.assertEqual(formatting.to_gsm7_text("Blåbærsyltetøy"), "Blåbærsyltetøy")


class DepartureFormattingTests(unittest.TestCase):
    def test_sms_marks_timetable_when_no_realtime(self):
        stop = make_stop([make_departure(), make_departure(
            aimed="2026-11-06T09:15:00+01:00", expected="2026-11-06T09:15:00+01:00", direction="Moss sentrum")])
        text = formatting.format_departures_sms(stop)
        self.assertIn("Skredderåsen linje 22", text)
        self.assertIn("08:39 mot Kambo", text)
        self.assertIn("09:15 mot Moss sentrum", text)
        self.assertIn("Rutetider (ikke sanntid).", text)
        self.assertTrue(sms.count_segments(text).gsm7_safe)

    def test_sms_marks_realtime(self):
        stop = make_stop([make_departure(realtime=True, expected="2026-11-06T08:42:00+01:00")])
        text = formatting.format_departures_sms(stop)
        self.assertIn("08:42", text)
        self.assertIn("(+3 min)", text)
        self.assertNotIn("Rutetider (ikke sanntid)", text)
        self.assertIn("Sanntid", text)

    def test_sms_cancellation_warning(self):
        stop = make_stop([make_departure(cancellation=True)])
        warnings = formatting.departure_warnings(stop)
        self.assertTrue(any("innstilt" in w for w in warnings))

    def test_sms_no_departures(self):
        stop = make_stop([], line_filter="99")
        text = formatting.format_departures_sms(stop)
        self.assertIn("ingen avganger", text)

    def test_deterministic(self):
        stop = make_stop([make_departure()])
        self.assertEqual(formatting.format_departures_sms(stop), formatting.format_departures_sms(stop))


class TripFormattingTests(unittest.TestCase):
    def test_sms_contains_line_direction_time_transfer(self):
        legs = [
            make_leg(),
            make_leg(start="2026-11-06T08:50:00+01:00", end="2026-11-06T09:03:00+01:00",
                     line="20", from_name="Moss bussterminal", to_name="Refsnes",
                     from_stop="NSR:StopPlace:2900", to_stop="NSR:StopPlace:3029"),
        ]
        itinerary = make_itinerary(legs)
        assessment = Assessment()
        assessment.transfers = [
            Transfer(
                at_stop_id="NSR:StopPlace:2900",
                at_stop_name="Moss bussterminal",
                from_line="22",
                to_line="20",
                arrival_time=legs[0].expected_end,
                departure_time=legs[1].expected_start,
                slack_s=120,
                minimum_s=120,
                is_short=False,
                is_warn_only=True,
            )
        ]
        text = formatting.format_trip_sms(itinerary, assessment)
        self.assertIn("Skredderåsen til Refsnes", text)
        self.assertIn("08:39 linje 22 mot Moss bussterminal", text)
        self.assertIn("bytte Moss bussterminal 2 min", text)
        self.assertIn("08:50 linje 20 mot Refsnes", text)
        self.assertIn("framme 09:03", text)
        self.assertIn("Rutetider.", text)
        self.assertIn("Kilde: Entur", text)
        self.assertTrue(sms.count_segments(text).gsm7_safe)

    def test_sms_scope_flag_is_visible(self):
        itinerary = make_itinerary([make_leg()])
        assessment = Assessment()
        assessment.scope = ScopeReport(
            status="FLAGG",
            outside=[{"name": "Oslo S", "stop_place_id": "NSR:StopPlace:337", "county_id": "KVE:TopographicPlace:03"}],
        )
        text = formatting.format_trip_sms(itinerary, assessment)
        self.assertIn("utenfor Østfold", text)
        self.assertIn("Oslo S", text)

    def test_warnings_cover_short_transfer_walk_and_scope(self):
        legs = [make_leg(distance=800.0, mode="foot", line=""), make_leg()]
        itinerary = make_itinerary(legs)
        assessment = Assessment()
        assessment.walk_total_m = 800.0
        assessment.walk_total_s = 600
        assessment.transfers = [
            Transfer("NSR:StopPlace:2900", "Moss bussterminal", "22", "20",
                     legs[0].expected_end, legs[1].expected_start, 60, 300, True, False)
        ]
        assessment.scope = ScopeReport(status="FLAGG", outside=[{"name": "Oslo S"}])
        warnings = formatting.itinerary_warnings(itinerary, assessment)
        joined = " | ".join(warnings)
        self.assertIn("kort bytte", joined)
        self.assertIn("gange 800 m", joined)
        self.assertIn("SCOPE-BRUD", joined)

    def test_steps_include_walk_and_transfer(self):
        walk = make_leg(mode="foot", line="", start="2026-11-06T08:30:00+01:00",
                        end="2026-11-06T08:39:00+01:00", from_name="Hjemme", to_name="Skredderåsen",
                        distance=450.0, duration=540)
        legs = [walk, make_leg(), make_leg(
            start="2026-11-06T09:05:00+01:00", end="2026-11-06T09:18:00+01:00", line="20",
            from_name="Moss bussterminal", to_name="Refsnes",
            from_stop="NSR:StopPlace:2900", to_stop="NSR:StopPlace:3029")]
        steps = formatting.itinerary_steps(make_itinerary(legs))
        joined = " | ".join(steps)
        self.assertIn("gå 450 m", joined)
        self.assertIn("bytte Moss bussterminal 17 min", joined)
        self.assertIn("framme 09:18", joined)


class IntentBlockTests(unittest.TestCase):
    def test_accepts_dict(self):
        lines = formatting.intent_block(
            {"kind": "DEPARTURES", "from_text": "skredderåsen", "line_code": "22",
             "time_text": "nå", "notes": ["x"]}
        )
        joined = "\n".join(lines)
        self.assertIn("AVGANGER", joined)
        self.assertIn("linje: 22", joined)


if __name__ == "__main__":
    unittest.main()
