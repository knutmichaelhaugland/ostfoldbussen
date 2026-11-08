"""Utgående SMS via inMobiles REST API.

API: POST https://api.inmobile.com/v4/sms/outgoing
Auth: Basic, vilkårlig brukernavn + API-nøkkel som passord.
Ingen retry ved timeout – en tvetydig feil kan ellers dobbeltsende.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .logging_setup import log
from .http_util import open_no_redirect
from prototype.sms import count_segments

API_URL = "https://api.inmobile.com/v4/sms/outgoing"


@dataclass
class InmobileSendResult:
    sent: bool
    suppressed: bool
    reason: str
    message_id: str | None = None
    segments: int = 0


def normalize_number(number: str) -> str:
    digits = "".join(ch for ch in str(number) if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = "47" + digits
    return digits


class InmobileSender:
    def __init__(self, config, db, http_post=None, clock=None):
        self.config = config
        self.db = db
        self.http_post = http_post or self._http_post
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def send(self, to_number: str, body: str, *, pseudonym: str | None = None,
             idempotency_key: str | None = None, request_id: int | None = None) -> InmobileSendResult:
        if not getattr(self.config, "inmobile_outbound_enabled", False):
            return InmobileSendResult(sent=False, suppressed=True, reason="inmobile_outbound_disabled")
        if not getattr(self.config, "inmobile_api_key", ""):
            return InmobileSendResult(sent=False, suppressed=True, reason="inmobile_api_key_missing")
        to = normalize_number(to_number)
        if not to:
            return InmobileSendResult(sent=False, suppressed=False, reason="invalid_number")
        now = self.clock()
        idem = idempotency_key or f"outbound:inmobile:{uuid.uuid4()}"
        reservation_segments = count_segments(body).segments
        delivery_id, reserve_reason = self.db.reserve_outbound_delivery(
            pseudonym=pseudonym,
            idempotency_key=idem,
            daily_limit=getattr(self.config, "daily_sms_limit", 0),
            rate_limit=getattr(self.config, "rate_limit_per_hour", 0),
            day=now.date().isoformat(),
            since_iso=(now - timedelta(hours=1)).isoformat(),
            segments=reservation_segments,
        )
        if delivery_id is None:
            log("inmobile_sms_suppressed", reason=reserve_reason)
            return InmobileSendResult(sent=False, suppressed=True, reason=reserve_reason)
        payload = {
            "messages": [{
                "to": to,
                "text": body,
                "from": getattr(self.config, "inmobile_from", ""),
                "encoding": "auto",
                "countryHint": "47",
            }]
        }
        try:
            response = self.http_post(API_URL, payload, self.config.inmobile_api_key)
        except urllib.error.HTTPError as exc:
            # 4xx er en avvist melding; 5xx/ukjent er tvetydig og må ikke
            # automatisk dobbeltsendes ved en ny webhook.
            status = "failed" if 400 <= exc.code < 500 else "unknown"
            self.db.finish_delivery(delivery_id, status)
            log("inmobile_sms_failed", status=exc.code)
            return InmobileSendResult(sent=False, suppressed=False, reason=f"http_{exc.code}")
        except Exception as exc:
            self.db.finish_delivery(delivery_id, "unknown")
            log("inmobile_sms_failed", error=type(exc).__name__)
            return InmobileSendResult(sent=False, suppressed=False, reason="send_failed")
        results = (response or {}).get("results") or []
        result = results[0] if results and isinstance(results[0], dict) else {}
        message_id = result.get("messageId")
        if not message_id:
            self.db.finish_delivery(delivery_id, "unknown")
            log("inmobile_sms_unknown_result")
            return InmobileSendResult(sent=False, suppressed=False, reason="invalid_response")
        try:
            segments = max(1, int(result.get("smsCount") or 1))
        except (TypeError, ValueError):
            segments = 1
        self.db.finish_delivery(
            delivery_id, "sent", segments=segments, provider_message_id=str(message_id)
        )
        log("inmobile_sms_sent", message_id=message_id, sms_count=segments)
        return InmobileSendResult(sent=True, suppressed=False, reason="sent",
                                  message_id=str(message_id), segments=segments)

    def _http_post(self, url: str, payload: dict, api_key: str) -> dict:
        credentials = base64.b64encode(f"ostfoldbussen:{api_key}".encode()).decode()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "ostfoldbussen/1.0",
            },
            method="POST",
        )
        with open_no_redirect(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
