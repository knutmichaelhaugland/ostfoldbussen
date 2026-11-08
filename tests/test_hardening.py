"""Regresjon for proxy-IP, 405-sikkerhetsheadere og generisk signaturfeil."""

import json
import tempfile
import unittest

from tests.helpers import RunningApp


class ProxyIpTests(unittest.TestCase):
    def test_forwarded_for_is_used_when_proxy_is_trusted(self):
        overrides = {"simulate_rate_limit_per_hour": 1, "trust_proxy": True, "trusted_proxy_ips": ("127.0.0.1",)}
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?"}).encode()
            first = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "203.0.113.11"})
            second = app.request("POST", "/api/simulate", body=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Forwarded-For": "203.0.113.11"})
            other = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "203.0.113.12"})
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)
        self.assertEqual(other.status, 200)


class MethodNotAllowedHeadersTests(unittest.TestCase):
    def test_405_uses_central_security_headers(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            response = app.request("PUT", "/")
        self.assertEqual(response.status, 405)
        self.assertIn("GET", response.headers["allow"])
        for header in ("x-content-type-options", "x-frame-options",
                       "content-security-policy", "x-request-id", "x-build-sha"):
            self.assertIn(header, response.headers)


class SignatureErrorTests(unittest.TestCase):
    def test_invalid_signature_does_not_leak_internal_reason(self):
        overrides = {
            "inmobile_webhook_enabled": True,
            "inmobile_webhook_key_id": "kid",
            "inmobile_webhook_public_key": "pk",
        }
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            response = app.request("POST", "/api/webhooks/inmobile", body=b"{}",
                                   headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 403)
        self.assertNotIn("missing_signature_headers", response.text)
        self.assertNotIn("reason", response.text)


class ProxySpoofTests(unittest.TestCase):
    def test_forwarded_for_is_ignored_without_trust_proxy(self):
        overrides = {"simulate_rate_limit_per_hour": 1, "trust_proxy": False}
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?"}).encode()
            first = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "203.0.113.21"})
            second = app.request("POST", "/api/simulate", body=body,
                                  headers={"Content-Type": "application/json",
                                           "X-Forwarded-For": "203.0.113.22"})
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)


class ConcurrentRateLimitTests(unittest.TestCase):
    def test_concurrent_simulate_requests_respect_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        overrides = {"simulate_rate_limit_per_hour": 3, "trust_proxy": False}
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?"}).encode()
            def call(_):
                return app.request("POST", "/api/simulate", body=body,
                                   headers={"Content-Type": "application/json"}).status
            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses = list(pool.map(call, range(8)))
        self.assertEqual(statuses.count(200), 3)
        self.assertEqual(statuses.count(429), 5)


class XffChainTests(unittest.TestCase):
    def test_last_forwarded_address_is_used_for_single_trusted_proxy(self):
        overrides = {"simulate_rate_limit_per_hour": 1, "trust_proxy": True, "trusted_proxy_ips": ("127.0.0.1",)}
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?"}).encode()
            first = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "198.51.100.1, 203.0.113.9"})
            second = app.request("POST", "/api/simulate", body=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Forwarded-For": "198.51.100.2, 203.0.113.9"})
            other = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "198.51.100.3, 203.0.113.10"})
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)
        self.assertEqual(other.status, 200)


class RateStatePruneTests(unittest.TestCase):
    def test_expired_state_is_removed_and_active_blocks_survive(self):
        from app.server import RATE_STATE_MAX_KEYS
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            now = 1_000_000.0
            app.ctx.simulate_hits = {"old": [now - 4000]}
            app.ctx.contact_hits = {"old": [now - 4000], "recent": [now - 10]}
            app.ctx.login_attempts = {"old": [now - 1000], "recent": [now - 10]}
            app.ctx.login_blocked = {"expired": now - 1, "active": now + 1000}
            for i in range(RATE_STATE_MAX_KEYS + 10):
                app.ctx.simulate_hits[f"ip-{i}"] = [now]
            # Sist innsettingsrekkefølge gjør at cap-eviction ikke fjerner
            # den ferske nøkkelen før de gamle IP-nøklene.
            app.ctx.simulate_hits["recent"] = [now - 10]
            app.ctx.prune_rate_state(now, force=True)
            self.assertNotIn("old", app.ctx.simulate_hits)
            self.assertIn("recent", app.ctx.simulate_hits)
            self.assertNotIn("old", app.ctx.contact_hits)
            self.assertIn("recent", app.ctx.contact_hits)
            self.assertNotIn("old", app.ctx.login_attempts)
            self.assertIn("recent", app.ctx.login_attempts)
            self.assertNotIn("expired", app.ctx.login_blocked)
            self.assertIn("active", app.ctx.login_blocked)
            self.assertLessEqual(len(app.ctx.simulate_hits), RATE_STATE_MAX_KEYS)


class UntrustedPeerTests(unittest.TestCase):
    def test_forwarded_for_ignored_from_untrusted_peer(self):
        overrides = {
            "simulate_rate_limit_per_hour": 1,
            "trust_proxy": True,
            "trusted_proxy_ips": ("192.0.2.0/24",),
        }
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?"}).encode()
            first = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "203.0.113.31"})
            second = app.request("POST", "/api/simulate", body=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Forwarded-For": "203.0.113.32"})
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)


class EmptyProxyAllowlistTests(unittest.TestCase):
    def test_empty_allowlist_never_trusts_xff(self):
        overrides = {"simulate_rate_limit_per_hour": 1, "trust_proxy": True,
                     "trusted_proxy_ips": ()}
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?"}).encode()
            first = app.request("POST", "/api/simulate", body=body,
                                headers={"Content-Type": "application/json",
                                         "X-Forwarded-For": "203.0.113.41"})
            second = app.request("POST", "/api/simulate", body=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Forwarded-For": "203.0.113.42"})
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)
