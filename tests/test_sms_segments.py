"""Enhetstester: GSM-7/UCS-2-segmentering , inkl. multipart 153/67."""

import unittest

from app.pipeline import _segment_trace


class SegmentTests(unittest.TestCase):
    def test_norwegian_letters_are_gsm7(self):
        trace = _segment_trace("Blåbærsyltetøy på Skredderåsen")
        self.assertEqual(trace["encoding"], "GSM-7")
        self.assertEqual(trace["segments"], 1)
        self.assertTrue(trace["gsm7_safe"])

    def test_gsm7_multipart_boundary_160_161(self):
        self.assertEqual(_segment_trace("a" * 160)["segments"], 1)
        self.assertEqual(_segment_trace("a" * 161)["segments"], 2)
        second = _segment_trace("a" * 161)
        self.assertEqual(second["per_segment"], 153)

    def test_gsm7_extension_char_costs_two(self):
        self.assertEqual(_segment_trace("a" * 159 + "€")["segments"], 2)

    def test_ucs2_for_non_gsm7_char(self):
        trace = _segment_trace("Buss 22 – Refsnes")
        self.assertEqual(trace["encoding"], "UCS-2")
        self.assertFalse(trace["gsm7_safe"])

    def test_ucs2_multipart_boundary_70_71_67(self):
        self.assertEqual(_segment_trace("–" * 70)["segments"], 1)
        self.assertEqual(_segment_trace("–" * 71)["segments"], 2)
        self.assertEqual(_segment_trace("–" * 134)["segments"], 2)
        self.assertEqual(_segment_trace("–" * 135)["segments"], 3)
        self.assertEqual(_segment_trace("–" * 71)["per_segment"], 67)

    def test_sms_drafts_from_pipeline_are_gsm7_safe(self):
        import tempfile

        from tests.helpers import RunningApp

        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            response = app.post_json(
                "/api/simulate",
                {"message": "Når går buss 22 fra Skredderåsen?"},
            )
            sms = response.json()["sms"]
            self.assertIn("encoding", sms["segments"])
            self.assertTrue(sms["segments"]["gsm7_safe"])
            self.assertGreaterEqual(sms["segments"]["segments"], 1)


if __name__ == "__main__":
    unittest.main()
