"""Enhetstester for deterministisk intensjonstolkning (ingen LLM)."""

import unittest
from datetime import datetime, timedelta

from prototype.intent import interpret

NOW = datetime.fromisoformat("2026-11-05T20:30:00+01:00")  # torsdag kveld


class DemoQuestionTests(unittest.TestCase):
    def test_departures_question(self):
        intent = interpret("Når går buss 22 fra Skredderåsen?", now=NOW)
        self.assertEqual(intent.kind, "DEPARTURES")
        self.assertEqual(intent.line_code, "22")
        self.assertEqual(intent.from_text, "skredderåsen")
        self.assertEqual(intent.to_text, "")
        self.assertEqual(intent.time_text, "nå")

    def test_trip_question(self):
        intent = interpret("Hvordan kommer jeg fra Skredderåsen til Refsnes?", now=NOW)
        self.assertEqual(intent.kind, "TRIP")
        self.assertEqual(intent.from_text, "skredderåsen")
        self.assertEqual(intent.to_text, "refsnes")

    def test_deterministic(self):
        a = interpret("Hvordan kommer jeg fra Skredderåsen til Refsnes?", now=NOW)
        b = interpret("Hvordan kommer jeg fra Skredderåsen til Refsnes?", now=NOW)
        self.assertEqual(a.__dict__, b.__dict__)


class VariantTests(unittest.TestCase):
    def test_bare_line_number_and_lowercase(self):
        intent = interpret("når går bussen 22 fra skredderåsen", now=NOW)
        self.assertEqual(intent.kind, "DEPARTURES")
        self.assertEqual(intent.line_code, "22")
        self.assertEqual(intent.from_text, "skredderåsen")

    def test_linje_keyword(self):
        intent = interpret("Når går linje 22 fra Skredderåsen?", now=NOW)
        self.assertEqual(intent.line_code, "22")

    def test_question_without_line(self):
        intent = interpret("Når går bussen fra Skredderåsen?", now=NOW)
        self.assertEqual(intent.kind, "DEPARTURES")
        self.assertEqual(intent.line_code, "")

    def test_missing_stop_is_noted(self):
        intent = interpret("Når går buss 22?", now=NOW)
        self.assertEqual(intent.kind, "DEPARTURES")
        self.assertTrue(any("mangler holdeplass" in n for n in intent.notes))

    def test_trip_with_i_morgen(self):
        intent = interpret("Hvordan reiser jeg fra Fredrikstad til Halden i morgen?", now=NOW)
        self.assertEqual(intent.kind, "TRIP")
        self.assertEqual(intent.to_text, "halden")
        target = datetime.fromisoformat(intent.target_datetime)
        self.assertEqual(target.date(), (NOW + timedelta(days=1)).date())

    def test_trip_with_clock(self):
        intent = interpret("Reise fra Skredderåsen til Refsnes i morgen kl. 10", now=NOW)
        self.assertEqual(intent.kind, "TRIP")
        target = datetime.fromisoformat(intent.target_datetime)
        self.assertEqual((target.hour, target.minute), (10, 0))
        self.assertEqual(target.date(), (NOW + timedelta(days=1)).date())

    def test_clock_in_past_rolls_to_next_day(self):
        intent = interpret("Når går buss 22 fra Skredderåsen kl 08:00?", now=NOW)
        target = datetime.fromisoformat(intent.target_datetime)
        self.assertEqual(target.date(), (NOW + timedelta(days=1)).date())
        self.assertTrue(any("passert" in n for n in intent.notes))

    def test_weekday(self):
        intent = interpret("Når går buss 22 fra Skredderåsen på søndag?", now=NOW)
        target = datetime.fromisoformat(intent.target_datetime)
        self.assertEqual(target.weekday(), 6)  # søndag

    def test_om_en_halvtime(self):
        intent = interpret("Når går bussen fra Skredderåsen om en halvtime?", now=NOW)
        target = datetime.fromisoformat(intent.target_datetime)
        self.assertEqual(int(target.timestamp() - NOW.timestamp()), 1800)

    def test_unknown(self):
        intent = interpret("Hva er været i Moss?", now=NOW)
        self.assertEqual(intent.kind, "UNKNOWN")

    def test_empty(self):
        intent = interpret("", now=NOW)
        self.assertEqual(intent.kind, "UNKNOWN")
        self.assertTrue(intent.notes)

    def test_til_without_fra_is_unknown(self):
        intent = interpret("Når går buss til Refsnes?", now=NOW)
        self.assertEqual(intent.kind, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
