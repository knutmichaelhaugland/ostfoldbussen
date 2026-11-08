"""Kontaktskjema: synlighet, validering og SMTP-fail-closed."""

import tempfile
import unittest
from unittest import mock
from urllib.parse import urlencode

from tests.helpers import RunningApp


class ContactPageTests(unittest.TestCase):
    def _app(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = RunningApp(tmp.name, overrides)
        app.__enter__()
        self.addCleanup(app.__exit__)
        return app

    def test_email_and_form_are_visible(self):
        html = self._app(public_contact_email="hjelp@ostfoldbussen.no").get("/kontakt").text
        self.assertIn("hjelp@ostfoldbussen.no", html)
        self.assertIn('action="/kontakt"', html)
        for field in ('name="name"', 'name="email"', 'name="message"',
                      'name="consent"', 'name="website"'):
            self.assertIn(field, html)
        button = html.split('class="sms-button contact-submit"', 1)[1].split(">", 1)[0]
        self.assertIn("disabled", button)  # SMTP ikke konfigurert i test

    def test_form_enabled_when_smtp_is_configured(self):
        html = self._app(
            public_contact_email="hjelp@ostfoldbussen.no",
            smtp_host="smtp.example.no",
            smtp_user="bruker",
            smtp_password="pass",
        ).get("/kontakt").text
        button = html.split('class="sms-button contact-submit"', 1)[1].split(">", 1)[0]
        self.assertNotIn("disabled", button)


class ContactSubmitTests(unittest.TestCase):
    def _app(self, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = RunningApp(tmp.name, overrides)
        app.__enter__()
        self.addCleanup(app.__exit__)
        return app

    def _post(self, app, data):
        return app.request(
            "POST", "/kontakt", body=urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_invalid_email_is_rejected(self):
        app = self._app()
        response = self._post(app, {"email": "ikke-epost", "message": "Hei", "consent": "1"})
        self.assertEqual(response.status, 400)
        self.assertIn("E-postadressen ser ikke riktig ut", response.text)

    def test_missing_consent_is_rejected(self):
        app = self._app()
        response = self._post(app, {"email": "a@example.no", "message": "Hei"})
        self.assertEqual(response.status, 400)
        self.assertIn("personvernserklæringen", response.text)

    def test_not_configured_fails_closed(self):
        app = self._app()
        response = self._post(app, {
            "email": "a@example.no", "message": "Hei", "consent": "1"})
        self.assertEqual(response.status, 503)

    @mock.patch("app.server.send_contact_email")
    def test_configured_form_sends_and_redirects(self, sender):
        app = self._app(
            smtp_host="smtp.example.no", smtp_user="bruker", smtp_password="pass",
            public_contact_email="hjelp@ostfoldbussen.no",
        )
        response = self._post(app, {
            "name": "Kari", "email": "kari@example.no",
            "message": "Hei, jeg lurer på bussen.", "consent": "1",
        })
        self.assertEqual(response.status, 303)
        self.assertIn("/kontakt?sendt=1", response.headers.get("location", ""))
        sender.assert_called_once()
        kwargs = sender.call_args.kwargs
        self.assertEqual(kwargs["email"], "kari@example.no")
        self.assertIn("bussen", kwargs["message"])

    def test_honeypot_pretends_success_without_sending(self):
        app = self._app()
        response = self._post(app, {
            "email": "a@example.no", "message": "Hei", "consent": "1",
            "website": "spam",
        })
        self.assertEqual(response.status, 303)


class SmtpTlsTests(unittest.TestCase):
    @mock.patch("app.contact.smtplib.SMTP")
    def test_starttls_uses_verified_context(self, smtp):
        from app.config import Config
        from app.contact import send_contact_email
        server = smtp.return_value
        send_contact_email(
            Config(smtp_host="smtp.example.no", smtp_user="u", smtp_password="p",
                   contact_to="to@example.no", smtp_starttls=True),
            name="Test", email="test@example.no", message="Hei",
        )
        context = server.starttls.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, 2)  # CERT_REQUIRED

    @mock.patch("app.contact.smtplib.SMTP_SSL")
    def test_implicit_tls_uses_verified_context(self, smtp_ssl):
        from app.config import Config
        from app.contact import send_contact_email
        send_contact_email(
            Config(smtp_host="smtp.example.no", smtp_port=465,
                   smtp_user="u", smtp_password="p", contact_to="to@example.no"),
            name="Test", email="test@example.no", message="Hei",
        )
        context = smtp_ssl.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, 2)


    @mock.patch("app.contact.smtplib.SMTP")
    @mock.patch("app.contact.smtplib.SMTP_SSL")
    def test_port_465_uses_implicit_tls_even_when_starttls_false(self, smtp_ssl, smtp):
        from app.config import Config
        from app.contact import send_contact_email
        send_contact_email(
            Config(smtp_host="smtp.example.no", smtp_port=465,
                   smtp_starttls=False, smtp_user="u", smtp_password="p",
                   contact_to="to@example.no"),
            name="Test", email="test@example.no", message="Hei",
        )
        smtp.assert_not_called()
        context = smtp_ssl.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, 2)
