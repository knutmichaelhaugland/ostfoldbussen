"""inMobile webhook: signaturfelt, payload-uttrekk og fail-closed rute."""

import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

from app.inmobile import extract_sms, verify_signature
from tests.helpers import RunningApp


class ExtractTests(unittest.TestCase):
    def test_json_payload(self):
        body = json.dumps({"message": "Når går bussen?", "sender": "+4790000000"}).encode()
        parsed = extract_sms(body, "application/json")
        self.assertEqual(parsed["message"], "Når går bussen?")
        self.assertEqual(parsed["sender"], "+4790000000")

    def test_nested_and_alternate_field_names(self):
        body = json.dumps({"data": {"text": "Hei", "msisdn": "4790000000"}}).encode()
        parsed = extract_sms(body, "application/json")
        self.assertEqual(parsed["message"], "Hei")
        self.assertEqual(parsed["sender"], "4790000000")

    def test_form_payload(self):
        body = b"message=Hei&from=%2B4790000000"
        parsed = extract_sms(body, "application/x-www-form-urlencoded")
        self.assertEqual(parsed["message"], "Hei")
        self.assertEqual(parsed["sender"], "+4790000000")


class SignatureTests(unittest.TestCase):
    def test_missing_headers_rejected(self):
        ok, reason = verify_signature({}, b"{}", "kid", "pk")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_signature_headers")

    @unittest.skipUnless(shutil.which("openssl"), "openssl mangler")
    def test_valid_ecdsa_p256_signature_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            priv = f"{tmp}/priv.pem"
            pub = f"{tmp}/pub.pem"
            der = f"{tmp}/pub.der"
            data = f"{tmp}/data.bin"
            sig = f"{tmp}/sig.bin"
            subprocess.run(["openssl", "genpkey", "-algorithm", "EC",
                            "-pkeyopt", "ec_paramgen_curve:P-256", "-out", priv],
                           check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-in", priv, "-pubout", "-out", pub],
                           check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-pubin", "-in", pub,
                            "-outform", "DER", "-out", der],
                           check=True, capture_output=True)
            timestamp = "2026-11-06T08:30:00Z"
            request_id = "test-request-1"
            body = b'{"message":"Hei","sender":"4790000000"}'
            payload = request_id.encode() + timestamp.encode() + body
            open(data, "wb").write(payload)
            subprocess.run(["openssl", "dgst", "-sha256", "-sign", priv,
                            "-out", sig, data], check=True, capture_output=True)
            pub_b64 = base64.b64encode(open(der, "rb").read()).decode()
            sig_b64 = base64.b64encode(open(sig, "rb").read()).decode()
            headers = {
                "X-Inmobile-Signature-Version": "1",
                "X-Inmobile-Request-Timestamp": timestamp,
                "X-Inmobile-Request-Id": request_id,
                "X-Inmobile-Signature-KeyId": "kid",
                "X-Inmobile-Signature": sig_b64,
            }
            fixed_now = datetime(2026, 11, 6, 8, 30, tzinfo=timezone.utc)
            ok, reason = verify_signature(headers, body, "kid", pub_b64, now=fixed_now)
            self.assertTrue(ok, reason)
            ok, reason = verify_signature(headers, body + b"x", "kid", pub_b64, now=fixed_now)
            self.assertFalse(ok)
            self.assertEqual(reason, "invalid_signature")


class RouteTests(unittest.TestCase):
    def test_webhook_is_closed_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp) as app:
            response = app.request(
                "POST", "/api/webhooks/inmobile", body=b"{}",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(response.status, 503)

    def test_bad_signature_is_rejected(self):
        overrides = {
            "inmobile_webhook_enabled": True,
            "inmobile_webhook_key_id": "kid",
            "inmobile_webhook_public_key": "pk",
        }
        with tempfile.TemporaryDirectory() as tmp, RunningApp(tmp, overrides) as app:
            response = app.request(
                "POST", "/api/webhooks/inmobile", body=b"{}",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(response.status, 403)


class ReplayDbTests(unittest.TestCase):
    def test_request_id_is_claimed_once(self):
        from app.db import Database, utc_now
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(f"{tmp}/app.db")
            db.init()
            self.assertTrue(db.claim_inmobile_request("abc", utc_now()))
            self.assertFalse(db.claim_inmobile_request("abc", utc_now()))


class WebhookEndToEndTests(unittest.TestCase):
    """Regresjon: gyldig inMobile-webhook skal faktisk sende ett svar."""

    @classmethod
    def setUpClass(cls):
        import shutil
        if not shutil.which("openssl"):
            raise unittest.SkipTest("openssl mangler")
        cls._tmp = tempfile.TemporaryDirectory()
        base = cls._tmp.name
        cls.priv = f"{base}/priv.pem"
        cls.pub_der = f"{base}/pub.der"
        pub_pem = f"{base}/pub.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC",
                        "-pkeyopt", "ec_paramgen_curve:P-256", "-out", cls.priv],
                       check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", cls.priv, "-pubout", "-out", pub_pem],
                       check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-pubin", "-in", pub_pem,
                        "-outform", "DER", "-out", cls.pub_der],
                       check=True, capture_output=True)
        cls.pub_b64 = base64.b64encode(open(cls.pub_der, "rb").read()).decode()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _headers(self, body: bytes, request_id: str) -> dict:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = request_id.encode() + timestamp.encode() + body
        data = f"{self._tmp.name}/{request_id}.data"
        sig = f"{self._tmp.name}/{request_id}.sig"
        open(data, "wb").write(payload)
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", self.priv,
                        "-out", sig, data], check=True, capture_output=True)
        return {
            "Content-Type": "application/json",
            "X-Inmobile-Signature-Version": "1",
            "X-Inmobile-Request-Timestamp": timestamp,
            "X-Inmobile-Request-Id": request_id,
            "X-Inmobile-Signature-KeyId": "kid",
            "X-Inmobile-Signature": base64.b64encode(open(sig, "rb").read()).decode(),
        }

    def _app(self, fake_post):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        overrides = {
            "inmobile_webhook_enabled": True,
            "inmobile_webhook_key_id": "kid",
            "inmobile_webhook_public_key": self.pub_b64,
            "inmobile_outbound_enabled": True,
            "inmobile_api_key": "key",
            "inmobile_from": "4700000000",
            "daily_sms_limit": 100,
            "inbound_rate_limit_per_hour": 100,
            "inbound_daily_limit": 100,
        }
        app = RunningApp(self.tmp.name, overrides, inmobile_http_post=fake_post)
        app.__enter__()
        self.addCleanup(lambda: (app.__exit__(), self.tmp.cleanup()))
        return app

    def test_valid_webhook_sends_one_reply(self):
        calls = []
        def fake(url, payload, key):
            calls.append((url, payload, key))
            return {"results": [{"messageId": "m1", "smsCount": 1}]}
        app = self._app(fake)
        body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                           "sender": "4790000000"}).encode()
        response = app.request("POST", "/api/webhooks/inmobile", body=body,
                               headers=self._headers(body, "req-1"))
        self.assertEqual(response.status, 200)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(app.ctx.inmobile_sender)
        self.assertEqual(app.ctx.db.get_counters().get("sms_out"), 1)
        self.assertEqual(app.ctx.db.recent_deliveries(1)[0]["status"], "sent")

    def test_duplicate_webhook_does_not_send_twice(self):
        calls = []
        def fake(url, payload, key):
            calls.append(1)
            return {"results": [{"messageId": "m2", "smsCount": 1}]}
        app = self._app(fake)
        body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                           "sender": "4790000000"}).encode()
        headers = self._headers(body, "req-2")
        first = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
        second = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 409)
        self.assertEqual(len(calls), 1)

    def test_inbound_rate_limit_is_applied(self):
        calls = []
        def fake(url, payload, key):
            calls.append(1)
            return {"results": [{"messageId": "m3", "smsCount": 1}]}
        app = self._app(fake)
        app.ctx.config = app.ctx.config.__class__(**{
            **app.ctx.config.__dict__, "inbound_rate_limit_per_hour": 1
        })
        first_body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                                 "sender": "4790000001"}).encode()
        second_body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                                  "sender": "4790000001"}).encode()
        first = app.request("POST", "/api/webhooks/inmobile", body=first_body,
                            headers=self._headers(first_body, "req-3a"))
        second = app.request("POST", "/api/webhooks/inmobile", body=second_body,
                             headers=self._headers(second_body, "req-3b"))
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(calls), 1)
        self.assertGreaterEqual(app.ctx.db.get_counters().get("inbound_rate_limited", 0), 1)

    def test_failed_processing_is_retried_once_and_then_succeeds(self):
        calls = []
        def fake(url, payload, key):
            calls.append(1)
            return {"results": [{"messageId": "m-retry", "smsCount": 1}]}
        app = self._app(fake)
        state = {"fail": True}
        pipeline_calls = []
        def flaky(message, **kwargs):
            pipeline_calls.append(message)
            if state["fail"]:
                raise RuntimeError("midlertidig pipeline-feil")
            return {"sms": {"text": "Svar"}, "request_id": 1, "result_type": "ANSWER"}
        app.ctx.pipeline.run = flaky
        body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                           "sender": "4790000004"}).encode()
        headers = self._headers(body, "req-retry-failed")
        first = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
        self.assertEqual(first.status, 500)
        self.assertEqual(len(pipeline_calls), 1)
        state["fail"] = False
        second = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(pipeline_calls), 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(app.ctx.db.get_counters().get("sms_out"), 1)

    def test_missing_empty_and_tampered_request_id_are_rejected(self):
        calls = []
        def fake(url, payload, key):
            calls.append(1)
            return {"results": [{"messageId": "m5", "smsCount": 1}]}
        app = self._app(fake)
        body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                           "sender": "4790000003"}).encode()
        good = self._headers(body, "req-id-good")
        missing = dict(good); missing.pop("X-Inmobile-Request-Id")
        empty = dict(good); empty["X-Inmobile-Request-Id"] = ""
        tampered = dict(good); tampered["X-Inmobile-Request-Id"] = "req-id-other"
        for headers in (missing, empty, tampered):
            response = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
            self.assertEqual(response.status, 403, headers)
        self.assertEqual(calls, [])

    def test_failed_send_can_be_retried(self):
        calls = []
        def fake(url, payload, key):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("midlertidig feil")
            return {"results": [{"messageId": "m4", "smsCount": 1}]}
        app = self._app(fake)
        body = json.dumps({"message": "Når går buss 22 fra Skredderåsen?",
                           "sender": "4790000002"}).encode()
        headers = self._headers(body, "req-4")
        first = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
        second = app.request("POST", "/api/webhooks/inmobile", body=body, headers=headers)
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 409)
        self.assertEqual(len(calls), 1)
        # Ukjent levering beholder kapasitetsreservasjonen: SMS-en kan være sendt.
        self.assertEqual(app.ctx.db.get_counters().get("sms_out"), 1)
        self.assertEqual(app.ctx.db.recent_deliveries(1)[0]["status"], "unknown")


class HeaderValidationTests(unittest.TestCase):
    def test_oversized_signed_fields_rejected_before_openssl(self):
        headers = {
            "X-Inmobile-Signature-Version": "1",
            "X-Inmobile-Request-Timestamp": "2026-11-06T08:30:00Z",
            "X-Inmobile-Request-Id": "x" * 257,
            "X-Inmobile-Signature-KeyId": "kid",
            "X-Inmobile-Signature": "AAAA",
        }
        ok, reason = verify_signature(headers, b"{}", "kid", "pk")
        self.assertFalse(ok)
        self.assertEqual(reason, "header_too_long")


class ClaimConcurrencyTests(unittest.TestCase):
    def test_claim_is_atomic_under_concurrency(self):
        import tempfile
        from concurrent.futures import ThreadPoolExecutor
        from app.db import Database, utc_now
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(f"{tmp}/app.db")
            db.init()
            with ThreadPoolExecutor(max_workers=8) as pool:
                claims = list(pool.map(
                    lambda _: db.claim_inmobile_request("same-request", utc_now()),
                    range(8),
                ))
            self.assertEqual(claims.count(True), 1)
            self.assertFalse(db.claim_inmobile_request("same-request", utc_now()))


class MessageLengthTests(unittest.TestCase):
    def test_inmobile_message_is_capped_before_pipeline(self):
        import base64
        import subprocess
        import tempfile
        from datetime import datetime, timezone
        from tests.helpers import RunningApp

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as keys:
            priv = f"{keys}/priv.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "EC",
                            "-pkeyopt", "ec_paramgen_curve:P-256", "-out", priv],
                           check=True, capture_output=True)
            pub = f"{keys}/pub.pem"
            subprocess.run(["openssl", "pkey", "-in", priv, "-pubout", "-out", pub],
                           check=True, capture_output=True)
            der = f"{keys}/pub.der"
            subprocess.run(["openssl", "pkey", "-pubin", "-in", pub,
                            "-outform", "DER", "-out", der],
                           check=True, capture_output=True)
            pub_b64 = base64.b64encode(open(der, "rb").read()).decode()
            overrides = {
                "max_message_chars": 40,
                "inmobile_webhook_enabled": True,
                "inmobile_webhook_key_id": "kid",
                "inmobile_webhook_public_key": pub_b64,
                "inbound_rate_limit_per_hour": 100,
                "inbound_daily_limit": 100,
            }
            with RunningApp(tmp, overrides) as app:
                captured = []
                app.ctx.pipeline.run = lambda message, **kwargs: (
                    captured.append(message) or {"sms": {}}
                )
                body = json.dumps({"message": "x" * 200, "sender": "4790000000"}).encode()
                rid = "length-req"
                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                payload = rid.encode() + stamp.encode() + body
                data = f"{keys}/data"
                sig = f"{keys}/sig"
                open(data, "wb").write(payload)
                subprocess.run(["openssl", "dgst", "-sha256", "-sign", priv,
                                "-out", sig, data], check=True, capture_output=True)
                headers = {
                    "Content-Type": "application/json",
                    "X-Inmobile-Signature-Version": "1",
                    "X-Inmobile-Request-Timestamp": stamp,
                    "X-Inmobile-Request-Id": rid,
                    "X-Inmobile-Signature-KeyId": "kid",
                    "X-Inmobile-Signature": base64.b64encode(open(sig, "rb").read()).decode(),
                }
                response = app.request("POST", "/api/webhooks/inmobile",
                                       body=body, headers=headers)
                self.assertEqual(response.status, 200)
                self.assertEqual(captured, ["x" * 40])
