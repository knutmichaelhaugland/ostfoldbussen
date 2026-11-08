"""vCard: innhold, escaping, foldning, sentralt nummer og fail-closed nedlasting."""

import tempfile
import unittest

from app.templates import _display_number
from app.vcard import build_vcard, international_tel
from tests.helpers import RunningApp


class VcardContentTests(unittest.TestCase):
    def test_fields_and_international_number(self):
        card = build_vcard("+4700000000")
        self.assertTrue(card.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n"))
        self.assertIn("FN:Østfoldbussen\r\n", card)
        self.assertIn("TEL;TYPE=CELL:+4700000000\r\n", card)
        self.assertIn("URL:https://ostfoldbussen.no\r\n", card)
        self.assertIn("NOTE:Send SMS til dette nummeret", card)
        self.assertIn("\r\nEND:VCARD\r\n", card)

    def test_utf8_and_special_characters_are_escaped(self):
        card = build_vcard("+4700000000")
        self.assertIn("Østfoldbussen", card)
        self.assertIn("\\,", card)  # komma i NOTE
        self.assertNotIn("\u00c3", card)  # ingen mojibake

    def test_number_is_normalized_from_local_format(self):
        self.assertEqual(international_tel("90000000"), "+4790000000")
        self.assertEqual(international_tel("+47 900 00 000"), "+4790000000")

    def test_lines_fold_at_75_octets(self):
        card = build_vcard("+4700000000")
        for line in card.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertIn("\r\n ", card)  # fortsettelseslinje

    def test_same_number_as_displayed(self):
        raw = "+4700000000"
        card = build_vcard(raw)
        self.assertIn("+4700000000", card)
        self.assertEqual(_display_number(raw).replace(" ", ""), "+4700000000")

    def test_invalid_number_rejected(self):
        with self.assertRaises(ValueError):
            build_vcard("+47123")


class VcardEndpointTests(unittest.TestCase):
    def test_download_headers_and_body(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, {
            "public_sms_enabled": True,
            "public_sms_number": "+4700000000",
        }) as app:
            response = app.get("/ostfoldbussen.vcf")
        self.assertEqual(response.status, 200)
        self.assertIn("text/vcard", response.headers["content-type"])
        self.assertIn("charset=utf-8", response.headers["content-type"])
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn('filename="ostfoldbussen.vcf"', response.headers["content-disposition"])
        self.assertIn("TEL;TYPE=CELL:+4700000000", response.text)
        self.assertNotIn("placeholder", response.text.lower())
        self.assertNotIn("build_sha", response.text.lower())

    def test_download_closed_before_activation(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            response = app.get("/ostfoldbussen.vcf")
            home = app.get("/").text
        self.assertEqual(response.status, 404)
        self.assertNotIn("ostfoldbussen.vcf", home)

    def test_button_and_tip_are_shown_with_active_number(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, {
            "public_sms_enabled": True,
            "public_sms_number": "+4700000000",
        }) as app:
            html = app.get("/").text
        text = " ".join(html.split())
        self.assertIn('href="/ostfoldbussen.vcf"', html)
        self.assertIn("Lagre nummeret i kontakter", html)
        self.assertIn("Da slipper du å huske nummeret", text)
