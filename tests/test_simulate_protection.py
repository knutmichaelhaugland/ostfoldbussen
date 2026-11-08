"""Tester for beskyttelse av /api/simulate (rate-limit + valgfri auth)."""

import tempfile
import unittest

from tests.helpers import RunningApp


class SimulateProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_rate_limit_returns_429(self):
        with RunningApp(self.tmp.name, {"simulate_rate_limit_per_hour": 3}) as app:
            for i in range(3):
                r = app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
                self.assertEqual(r.status, 200, f"forsøk {i}")
            r = app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            self.assertEqual(r.status, 429)
            self.assertEqual(r.json()["error"], "rate_limited")

    def test_zero_limit_means_disabled(self):
        with RunningApp(self.tmp.name, {"simulate_rate_limit_per_hour": 0}) as app:
            for _ in range(5):
                r = app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
                self.assertEqual(r.status, 200)

    def test_auth_required_when_enabled(self):
        with RunningApp(self.tmp.name, {"simulate_require_auth": True}) as app:
            r = app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            self.assertEqual(r.status, 401)
            self.assertEqual(r.json()["error"], "auth_required")

    def test_auth_not_required_by_default(self):
        with RunningApp(self.tmp.name) as app:
            r = app.post_json("/api/simulate", {"message": "Når går buss 22 fra Skredderåsen?"})
            self.assertEqual(r.status, 200)


class SimulateDefaultSecurityTests(unittest.TestCase):
    def test_production_config_requires_auth_by_default(self):
        from app.config import Config
        self.assertTrue(Config().simulate_require_auth)

    def test_conversation_namespaces_are_isolated_between_sessions(self):
        import tempfile
        from app import auth
        from tests.helpers import RunningApp
        with tempfile.TemporaryDirectory() as tmp:
            with RunningApp(tmp, {"simulate_require_auth": True}) as app:
                def token(user):
                    return auth.sign_session(app.config.session_secret, user)
                for user in ("a", "b"):
                    response = app.post_json(
                        "/api/simulate",
                        {"message": "Skredderåsen til Refsnes", "conversation_id": "shared"},
                        cookies={app.config.session_cookie: token(user)},
                    )
                    self.assertEqual(response.status, 200, response.text)
                self.assertIsNotNone(app.ctx.db.load_conversation("api:a:shared"))
                self.assertIsNotNone(app.ctx.db.load_conversation("api:b:shared"))
