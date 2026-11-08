"""Enhetstester for Entur-klienten: validering, 429-backoff, headere."""

import json
import unittest
from datetime import datetime, timezone

from prototype import config
from prototype.entur_client import (
    EnturClient,
    EnturGraphQLError,
    EnturHTTPError,
    EnturRateLimited,
    EnturTransportError,
    HttpResponse,
    parse_rate_limit_expiry,
)


def response(status=200, payload=None, headers=None, text=None):
    body = text.encode() if text is not None else json.dumps(payload or {}).encode()
    return HttpResponse(status=status, headers=headers or {}, body=body, url="test")


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, headers, body=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
            }
        )
        if not self.responses:
            raise AssertionError("uventet ekstra kall")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ClientTests(unittest.TestCase):
    def make_client(self, responses, max_retries=3, capture_raw=False):
        transport = FakeTransport(responses)
        sleeps = []
        client = EnturClient(
            transport=transport,
            max_retries=max_retries,
            sleep=sleeps.append,
            clock=lambda: 1_000_000.0,
            capture_raw=capture_raw,
        )
        return client, transport, sleeps

    def test_sends_client_name_header(self):
        client, transport, _ = self.make_client([response(200, {"data": {"x": 1}})])
        data = client.graphql("{ x }")
        self.assertEqual(data, {"x": 1})
        self.assertEqual(
            transport.requests[0]["headers"]["ET-Client-Name"], "ostfoldbussen-selfhosted"
        )
        self.assertEqual(transport.requests[0]["method"], "POST")
        self.assertEqual(transport.requests[0]["url"], config.JOURNEY_PLANNER_URL)

    def test_graphql_errors_with_null_data_raises(self):
        client, _, _ = self.make_client(
            [response(200, {"data": None, "errors": [{"message": "InvalidSyntax"}]})]
        )
        with self.assertRaises(EnturGraphQLError) as ctx:
            client.graphql("{ ugyldig }")
        self.assertIn("InvalidSyntax", str(ctx.exception))

    def test_null_data_without_errors_raises(self):
        client, _, _ = self.make_client([response(200, {"data": None})])
        with self.assertRaises(EnturGraphQLError):
            client.graphql("{ x }")

    def test_partial_errors_returns_data_and_exposes_errors(self):
        client, _, _ = self.make_client(
            [
                response(
                    200,
                    {"data": {"stopPlace": {"id": "x"}}, "errors": [{"message": "delvis feil"}]},
                )
            ]
        )
        data = client.graphql("{ x }")
        self.assertEqual(data["stopPlace"]["id"], "x")
        self.assertEqual(len(client.partial_errors), 1)

    def test_http_400_raises_with_status(self):
        client, _, _ = self.make_client([response(400, text="Invalid parameters")])
        with self.assertRaises(EnturHTTPError) as ctx:
            client.graphql("{ x }")
        self.assertEqual(ctx.exception.status, 400)

    def test_timeout_raises_transport_error(self):
        client, _, _ = self.make_client([EnturTransportError("timeout")])
        with self.assertRaises(EnturTransportError):
            client.graphql("{ x }")

    def test_429_reads_rate_limit_expiry_time_and_waits(self):
        # now = 1_000_000.0 -> 2026-11-05T18:34:47Z er langt fram; bruk
        # en expiry som parseren kan lese og som gir positiv ventetid.
        headers = {"rate-limit-expiry-time": "Thu Nov 05 2026 18:34:47 GMT-0000 (GMT)"}
        client, transport, sleeps = self.make_client(
            [response(429, {"fault": {"faultstring": "quota"}}, headers), response(200, {"data": {"ok": 1}})]
        )
        data = client.graphql("{ x }")
        self.assertEqual(data, {"ok": 1})
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)
        self.assertLessEqual(sleeps[0], 65.05)
        self.assertEqual(transport.requests[1]["headers"]["ET-Client-Name"], "ostfoldbussen-selfhosted")

    def test_429_without_headers_uses_exponential_backoff(self):
        client, _, sleeps = self.make_client(
            [response(429, {"fault": {}}), response(429, {"fault": {}}), response(200, {"data": {}})]
        )
        client.graphql("{ x }")
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_429_after_retries_raises(self):
        client, _, _ = self.make_client(
            [response(429, {"fault": {}}) for _ in range(4)], max_retries=3
        )
        with self.assertRaises(EnturRateLimited):
            client.graphql("{ x }")

    def test_geocoder_returns_geojson_without_data_envelope(self):
        client, transport, _ = self.make_client(
            [response(200, {"type": "FeatureCollection", "features": []})]
        )
        payload = client.geocoder_autocomplete({"q": "x"})
        self.assertEqual(payload["features"], [])
        self.assertIn("q=x", transport.requests[0]["url"])
        self.assertEqual(transport.requests[0]["headers"]["ET-Client-Name"], "ostfoldbussen-selfhosted")

    def test_geocoder_fault_raises(self):
        client, _, _ = self.make_client([response(200, {"fault": {"faultstring": "nope"}})])
        with self.assertRaises(EnturGraphQLError):
            client.geocoder_place(["NSR:StopPlace:1"])

    def test_capture_raw_records_bodies(self):
        client, _, _ = self.make_client(
            [response(200, {"data": {"ok": 1}})], capture_raw=True
        )
        client.graphql("{ x }")
        self.assertEqual(len(client.raw_captures), 1)
        self.assertIn('"ok"', client.raw_captures[0]["body"])

    def test_server_error_retries_then_raises(self):
        client, _, sleeps = self.make_client(
            [response(500, text="boom") for _ in range(4)], max_retries=3
        )
        with self.assertRaises(EnturHTTPError):
            client.graphql("{ x }")
        self.assertEqual(len(sleeps), 3)


class ExpiryParseTests(unittest.TestCase):
    def test_parses_observed_format(self):
        expiry = datetime(2026, 11, 5, 18, 34, 47, tzinfo=timezone.utc).timestamp()
        now = expiry - 7
        self.assertAlmostEqual(
            parse_rate_limit_expiry("Thu Nov 05 2026 18:34:47 GMT-0000 (GMT)", now=now),
            7.0,
            places=2,
        )

    def test_past_expiry_returns_zero(self):
        now = datetime(2026, 11, 5, 19, 0, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(
            parse_rate_limit_expiry("Thu Nov 05 2026 18:34:47 GMT-0000 (GMT)", now=now), 0.0
        )

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_rate_limit_expiry("ikke en dato"))
        self.assertIsNone(parse_rate_limit_expiry(None))

    def test_double_digit_day(self):
        self.assertIsNotNone(
            parse_rate_limit_expiry("Thu Nov 05 2026 18:34:47 GMT-0000 (GMT)", now=0)
        )


if __name__ == "__main__":
    unittest.main()
