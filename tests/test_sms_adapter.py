"""Kontraktstest: en minimal SMS-adapter kan kobles til uten reiselogikkendring."""

import tempfile
import unittest

from app.sms_adapter import (
    DeliveryStatus,
    InboundSms,
    InboundVerification,
    SmsAdapter,
    SmsSendResult,
)
from tests.helpers import RunningApp


class FakeSmsAdapter:
    name = "fake"

    def __init__(self):
        self.claimed = []
        self.sent = []
        self.statuses = []

    def verify_inbound(self, headers, body):
        return InboundVerification(
            True, "valid",
            InboundSms("fake", "fake-req-1", "4790000000",
                       "Når går buss 22 fra Skredderåsen?"),
        )

    def claim_inbound(self, inbound):
        if inbound.request_id in self.claimed:
            return False
        self.claimed.append(inbound.request_id)
        return True

    def mark_inbound(self, inbound, status):
        self.statuses.append((inbound.request_id, status))

    def send(self, to_number, body, *, pseudonym, idempotency_key, request_id=None):
        self.sent.append((to_number, body, idempotency_key))
        return SmsSendResult(True, False, "sent", "provider-1", 1)

    def parse_status(self, params):
        return None


class SmsAdapterContractTests(unittest.TestCase):
    def test_fake_adapter_is_protocol_compatible(self):
        self.assertIsInstance(FakeSmsAdapter(), SmsAdapter)

    def test_fake_adapter_handles_inbound_through_existing_core(self):
        fake = FakeSmsAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            overrides = {"inmobile_webhook_enabled": True}
            with RunningApp(tmp, overrides, sms_adapter=fake) as app:
                response = app.request(
                    "POST", "/api/webhooks/inmobile", body=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(len(fake.sent), 1)
                self.assertEqual(fake.claimed, ["fake-req-1"])
                self.assertIn(("fake-req-1", "completed"), fake.statuses)
