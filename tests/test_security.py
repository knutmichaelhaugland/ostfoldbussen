"""Sikkerhetstester: hemmelighetslekkasje, logging, cookies og path traversal."""

import json
import logging
import tempfile
import unittest
from urllib.parse import urlencode

from tests.helpers import RunningApp


class NoSecretLeakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = RunningApp(
            self.tmp.name,
            {
                "inmobile_api_key": "hemmelig-inmobile-nokkel",
                "inmobile_outbound_enabled": True,
                "inmobile_from": "4700000000",
                "llm_api_key": "hemmelig-llm-nokkel",
            },
        )
        self.app.__enter__()
        self.secrets = [
            self.app.config.admin_password_hash,
            self.app.config.session_secret,
            self.app.config.pseudonym_salt,
            "hemmelig-inmobile-nokkel",
            "hemmelig-llm-nokkel",
        ]

    def tearDown(self):
        self.app.__exit__()
        self.tmp.cleanup()

    def test_public_pages_have_no_secrets(self):
        for path in ("/", "/slik-fungerer-det", "/om", "/personvern", "/data", "/status"):
            text = self.app.get(path).text
            for secret in self.secrets:
                self.assertNotIn(secret, text, path)

    def test_healthz_and_simulate_have_no_secrets(self):
        texts = [
            self.app.get("/healthz").text,
            self.app.post_json(
                "/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"}
            ).text,
        ]
        for text in texts:
            for secret in self.secrets:
                self.assertNotIn(secret, text)

    def test_cookies_are_http_only_and_secure_when_configured(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            with RunningApp(tmp.name, {"cookie_secure": True}) as app:
                page = app.get("/admin")
                cookie = page.headers["set-cookie"].lower()
                self.assertIn("httponly", cookie)
                self.assertIn("secure", cookie)
                self.assertIn("samesite=lax", cookie)
        finally:
            tmp.cleanup()


class LoggingPrivacyTests(unittest.TestCase):
    def test_no_phone_or_message_in_logs(self):
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.getLogger("ostfoldbussen")
        handler = Capture()
        logger.addHandler(handler)
        tmp = tempfile.TemporaryDirectory()
        try:
            with RunningApp(tmp.name) as app:
                self.app = app
                phone = "+4798765432"
                message = "Når går buss 22 fra Skredderåsen?"
                app.post_json("/api/simulate", {"message": message})
        finally:
            logger.removeHandler(handler)
            tmp.cleanup()
        rendered = "\n".join(record.getMessage() + json.dumps(getattr(record, "fields", {}), default=str) for record in records)
        self.assertNotIn(phone, rendered)
        self.assertNotIn("98765432", rendered)
        self.assertNotIn("Skredderåsen", rendered)


class TrafficTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = RunningApp(cls.tmp.name)
        cls.app.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.app.__exit__()
        cls.tmp.cleanup()

    def test_path_traversal_returns_404(self):
        for path in ("/../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/static/../../etc/passwd"):
            self.assertEqual(self.app.get(path).status, 404, path)

    def test_pseudonym_not_reversible_or_phone(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            response = app.post_json(
                "/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"}
            )
            self.assertEqual(response.status, 200)
        # Simulate har ingen avsender; sjekk pseudonymfunksjonen direkte
        from app.pipeline import pseudonymize

        pseudonym = pseudonymize("salt-0123456789abcdef", "+4798765432")
        self.assertEqual(len(pseudonym), 64)
        self.assertNotIn("98765432", pseudonym)
        self.assertNotEqual(pseudonym, pseudonymize("annet-salt-0123456789", "+4798765432"))

    def test_unknown_admin_route_requires_auth(self):
        self.assertEqual(self.app.get("/admin/hemmelig").status, 401)

    def test_error_responses_have_security_headers(self):
        response = self.app.get("/finnes-ikke")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("default-src", response.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
