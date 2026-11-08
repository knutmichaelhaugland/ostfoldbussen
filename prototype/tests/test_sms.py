"""Enhetstester for SMS-segmenttelling (GSM-7 / UCS-2)."""

import unittest

from prototype import sms


class Gsm7Tests(unittest.TestCase):
    def test_norwegian_letters_are_gsm7(self):
        info = sms.count_segments("Blåbærsyltetøy på Skredderåsen")
        self.assertEqual(info.encoding, "GSM-7")
        self.assertTrue(info.gsm7_safe)
        self.assertEqual(info.segments, 1)

    def test_boundary_160_is_one_segment(self):
        info = sms.count_segments("a" * 160)
        self.assertEqual(info.segments, 1)
        self.assertEqual(info.per_segment, 160)

    def test_boundary_161_is_two_segments(self):
        info = sms.count_segments("a" * 161)
        self.assertEqual(info.segments, 2)
        self.assertEqual(info.per_segment, 153)

    def test_extension_char_costs_two_septets(self):
        self.assertEqual(sms.gsm7_units("€"), 2)
        self.assertEqual(sms.gsm7_units("{}"), 4)
        info = sms.count_segments("a" * 159 + "€")
        self.assertEqual(info.segments, 2)  # 161 septeter

    def test_153_boundary_multipart(self):
        self.assertEqual(sms.count_segments("a" * 306).segments, 2)
        self.assertEqual(sms.count_segments("a" * 307).segments, 3)


class Ucs2Tests(unittest.TestCase):
    def test_non_gsm_char_forces_ucs2(self):
        info = sms.count_segments("Buss 22 – Refsnes")  # en dash
        self.assertEqual(info.encoding, "UCS-2")
        self.assertFalse(info.gsm7_safe)
        self.assertEqual(info.segments, 1)

    def test_ucs2_boundaries(self):
        # En dash er ikke i GSM-7 og tvinger UCS-2.
        self.assertEqual(sms.count_segments("–" * 70).segments, 1)
        self.assertEqual(sms.count_segments("–" * 71).segments, 2)
        self.assertEqual(sms.count_segments("–" * 134).segments, 2)
        self.assertEqual(sms.count_segments("–" * 135).segments, 3)

    def test_emoji_counts_utf16_units(self):
        # Emoji er 2 UTF-16-kodeenheter.
        info = sms.count_segments("🚌")
        self.assertEqual(info.encoding, "UCS-2")
        self.assertEqual(info.units, 2)

    def test_empty_message_one_segment(self):
        info = sms.count_segments("")
        self.assertEqual(info.segments, 1)
        self.assertEqual(info.units, 0)


if __name__ == "__main__":
    unittest.main()
