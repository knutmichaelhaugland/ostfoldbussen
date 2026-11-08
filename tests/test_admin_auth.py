"""Admin-autentisering, session-cookie og admin-sider."""

import tempfile
import unittest

from tests.helpers import RunningApp


ADMIN_PATHS = ("/admin/health", "/admin/requests", "/admin/errors", "/admin/costs")


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = RunningApp(self.tmp.name)
        self.app.__enter__()

    def tearDown(self):
        self.app.__exit__()
        self.tmp.cleanup()

    def test_admin_pages_require_auth(self):
        for path in ADMIN_PATHS:
            response = self.app.get(path)
            self.assertEqual(response.status, 401, path)
            self.assertNotIn("Innloggingsside", response.text)

    def test_login_page_sets_csrf_cookie(self):
        response = self.app.get("/admin")
        self.assertEqual(response.status, 200)
        self.assertIn('name="csrf"', response.text)
        self.assertIn("ob_csrf", response.cookies)
        self.assertIn("httponly", response.headers["set-cookie"].lower())

    def test_login_without_csrf_rejected(self):
        response = self.app.post_form(
            "/admin/login", {"username": "admin", "password": "correct horse battery"}
        )
        self.assertEqual(response.status, 400)

    def test_login_with_mismatched_csrf_rejected(self):
        page = self.app.get("/admin")
        response = self.app.post_form(
            "/admin/login",
            {"csrf": "feil", "username": "admin", "password": "correct horse battery"},
            cookies=page.cookies,
        )
        self.assertEqual(response.status, 400)

    def test_wrong_password_rejected(self):
        page = self.app.get("/admin")
        response = self.app.post_form(
            "/admin/login",
            {"csrf": page.cookies["ob_csrf"], "username": "admin", "password": "feil"},
            cookies=page.cookies,
        )
        self.assertEqual(response.status, 401)
        self.assertNotIn("ob_session", response.cookies)

    def test_wrong_username_rejected(self):
        page = self.app.get("/admin")
        response = self.app.post_form(
            "/admin/login",
            {"csrf": page.cookies["ob_csrf"], "username": "annen", "password": "correct horse battery"},
            cookies=page.cookies,
        )
        self.assertEqual(response.status, 401)

    def test_all_login_posts_are_rate_limited_without_credential_lockout(self):
        # Ugyldig CSRF skal ikke gi permanent credential-lockout, men alle
        # login-POSTs skal ha en egen kortvarig ressursgrense.
        for _ in range(5):
            response = self.app.post_form(
                "/admin/login", {"username": "admin", "password": "feil"})
            self.assertEqual(response.status, 400)
        response, _ = self.app.login()
        self.assertEqual(response.status, 303)
        # 5 ugyldige + 1 vellykket + 24 ugyldige = 30 POST-er i vinduet.
        for _ in range(24):
            response = self.app.post_form(
                "/admin/login", {"username": "admin", "password": "feil"})
            self.assertEqual(response.status, 400)
        limited = self.app.post_form(
            "/admin/login", {"username": "admin", "password": "feil"})
        self.assertEqual(limited.status, 429)

    def test_successful_login_and_admin_pages(self):
        response, cookies = self.app.login()
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["location"], "/admin/health")
        self.assertIn("ob_session", cookies)
        session_cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", session_cookie)
        self.assertIn("samesite=lax", session_cookie)
        for path in ADMIN_PATHS:
            page = self.app.get(path, cookies=cookies)
            self.assertEqual(page.status, 200, path)
        self.assertIn("Forespørsler", self.app.get("/admin/health", cookies=cookies).text)

    def test_tampered_session_cookie_is_401(self):
        _, cookies = self.app.login()
        tampered = dict(cookies)
        tampered["ob_session"] = tampered["ob_session"][:-2] + "AA"
        self.assertEqual(self.app.get("/admin/health", cookies=tampered).status, 401)

    def test_logout_requires_post_and_csrf(self):
        _, cookies = self.app.login()
        page = self.app.get("/admin/health", cookies=cookies)
        self.assertEqual(page.status, 200)
        token = page.text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        self.assertIn("ob_csrf", page.cookies)
        bad = self.app.get("/admin/logout", cookies=cookies)
        self.assertEqual(bad.status, 405)
        missing = self.app.post_form("/admin/logout", {}, cookies=cookies)
        self.assertEqual(missing.status, 400)
        response = self.app.post_form(
            "/admin/logout", {"csrf": token}, cookies={**cookies, **page.cookies}
        )
        self.assertEqual(response.status, 303)
        set_cookie = response.headers["set-cookie"].lower()
        self.assertIn("max-age=0", set_cookie)

    def test_admin_pages_do_not_leak_secrets(self):
        _, cookies = self.app.login()
        secrets = [
            self.app.config.admin_password_hash,
            self.app.config.session_secret,
            self.app.config.pseudonym_salt,
            self.app.config.inmobile_api_key or "inmobile-token",
        ]
        for path in ADMIN_PATHS + ("/admin",):
            text = self.app.get(path, cookies=cookies if path in ADMIN_PATHS else None).text
            for secret in secrets:
                self.assertNotIn(secret, text, path)

    def test_login_rate_limit(self):
        page = self.app.get("/admin")
        for _ in range(10):
            self.app.post_form(
                "/admin/login",
                {"csrf": page.cookies["ob_csrf"], "username": "admin", "password": "feil"},
                cookies=page.cookies,
            )
        response = self.app.post_form(
            "/admin/login",
            {"csrf": page.cookies["ob_csrf"], "username": "admin", "password": "feil"},
            cookies=page.cookies,
        )
        self.assertEqual(response.status, 429)


class AdminContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = RunningApp(self.tmp.name)
        self.app.__enter__()
        _, self.cookies = self.app.login()
        self.app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})

    def tearDown(self):
        self.app.__exit__()
        self.tmp.cleanup()

    def test_requests_page_shows_pseudonym_not_message(self):
        page = self.app.get("/admin/requests", cookies=self.cookies)
        self.assertEqual(page.status, 200)
        self.assertIn("result_type", page.text)
        self.assertNotIn("Skredderåsen", page.text)

    def test_costs_page_shows_counters_and_unknown_prices(self):
        page = self.app.get("/admin/costs", cookies=self.cookies)
        self.assertEqual(page.status, 200)
        self.assertIn("Kostnader", page.text)
        self.assertIn("UKJENT", page.text)
        self.assertIn("requests", page.text)

    def test_health_page(self):
        page = self.app.get("/admin/health", cookies=self.cookies)
        self.assertEqual(page.status, 200)
        self.assertIn("Helse", page.text)
        self.assertIn("NOT CONFIGURED", page.text)
        self.assertIn("DISABLED", page.text)

    def test_errors_page(self):
        page = self.app.get("/admin/errors", cookies=self.cookies)
        self.assertEqual(page.status, 200)
        self.assertIn("Feil", page.text)


if __name__ == "__main__":
    unittest.main()
