"""Web-tester: offentlige sider, /healthz og /status."""

import tempfile
import unittest

from tests.helpers import RunningApp, fake_probe_factory


class PublicPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = RunningApp(cls.tmp.name)
        cls.app.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.app.__exit__()
        cls.tmp.cleanup()

    def test_public_pages_return_200(self):
        for path in ("/", "/slik-fungerer-det", "/om", "/personvern", "/data", "/status"):
            response = self.app.get(path)
            self.assertEqual(response.status, 200, path)
            self.assertIn("text/html", response.headers["content-type"])
            self.assertIn("Østfoldbussen", response.text)

    def test_data_page_has_nlod_attribution(self):
        text = self.app.get("/data").text
        self.assertIn("NLOD", text)
        self.assertIn("Entur", text)

    def test_404(self):
        response = self.app.get("/finnes-ikke")
        self.assertEqual(response.status, 404)

    def test_security_headers(self):
        response = self.app.get("/")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_favicon(self):
        self.assertEqual(self.app.get("/favicon.ico").status, 204)

    def test_api_get_method_not_allowed(self):
        response = self.app.get("/api/simulate")
        self.assertEqual(response.status, 405)
        self.assertIn("GET", response.headers["allow"])


class HealthzTests(unittest.TestCase):
    def _health(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, **kwargs) as app:
            return app.get("/healthz")

    def test_healthy_state_is_honest(self):
        response = self._health()
        self.assertEqual(response.status, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        components = payload["components"]
        self.assertEqual(components["entur"]["state"], "OK")
        self.assertIsNotNone(components["entur"]["last_success"])
        self.assertEqual(components["db"]["state"], "OK")
        self.assertEqual(components["llm"]["state"], "NOT CONFIGURED")
        self.assertEqual(components["sms"]["state"], "DISABLED")
        self.assertEqual(payload["build_sha"], "testsha")
        self.assertGreaterEqual(payload["uptime_s"], 0)

    def test_degraded_entur_is_not_fake_healthy(self):
        response = self._health(probe=fake_probe_factory("DEGRADED"))
        self.assertEqual(response.status, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["components"]["entur"]["state"], "DEGRADED")

    def test_entur_exception_is_degraded(self):
        response = self._health(probe=fake_probe_factory(RuntimeError("nede")))
        self.assertEqual(response.status, 503)
        self.assertEqual(response.json()["components"]["entur"]["state"], "DEGRADED")

    def test_health_check_disabled_is_unknown_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(
            tmp, config_overrides={"health_entur_check": False}
        ) as app:
            response = app.get("/healthz")
        self.assertEqual(response.status, 503)
        payload = response.json()
        self.assertEqual(payload["components"]["entur"]["state"], "UNKNOWN")

    def test_status_page_hides_internal_details(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            response = app.get("/status")
        self.assertEqual(response.status, 200)
        self.assertIn("Driftsstatus", response.text)
        self.assertNotIn("fake ok", response.text)
        self.assertNotIn("last_success", response.text)


if __name__ == "__main__":
    unittest.main()
