"""inMobile-implementasjon av SMS-adaptergrensesnittet."""
from __future__ import annotations

from typing import Mapping

from .db import utc_now
from .inmobile import MAX_REQUEST_ID_LEN, extract_sms, verify_signature
from .inmobile_sender import InmobileSender
from .logging_setup import log
from .sms_adapter import (
    DeliveryStatus,
    InboundSms,
    InboundVerification,
    SmsSendResult,
)


class InmobileAdapter:
    name = "inmobile"

    def __init__(self, config, db, sender: InmobileSender):
        self.config = config
        self.db = db
        self.sender = sender

    def verify_inbound(self, headers: Mapping[str, str], body: bytes) -> InboundVerification:
        lower = {str(k).lower(): v for k, v in headers.items()}
        ok, reason = verify_signature(
            lower, body,
            key_id=self.config.inmobile_webhook_key_id,
            public_key_b64=self.config.inmobile_webhook_public_key,
        )
        if not ok:
            log("inmobile_signature_rejected", reason=reason)
            try:
                self.db.increment_counter("security_invalid_signature")
            except Exception:
                pass
            return InboundVerification(False, reason)
        request_id = lower.get("x-inmobile-request-id", "")
        if not request_id or len(request_id) > MAX_REQUEST_ID_LEN:
            return InboundVerification(False, "invalid_request_id")
        parsed = extract_sms(body, lower.get("content-type", ""))
        log("inmobile_webhook", fields=",".join(parsed["fields"])[:300],
            has_message=bool(parsed["message"]), has_sender=bool(parsed["sender"]))
        inbound = InboundSms(
            provider=self.name,
            request_id=request_id,
            sender=parsed["sender"],
            message=parsed["message"],
        )
        return InboundVerification(True, "valid", inbound)

    def claim_inbound(self, inbound: InboundSms) -> bool:
        return self.db.claim_inmobile_request(inbound.request_id, utc_now())

    def mark_inbound(self, inbound: InboundSms, status: str) -> None:
        self.db.mark_inmobile_request(inbound.request_id, status)

    def send(self, to_number: str, body: str, *, pseudonym: str | None,
             idempotency_key: str, request_id: int | None = None) -> SmsSendResult:
        result = self.sender.send(
            to_number, body, pseudonym=pseudonym,
            idempotency_key=idempotency_key, request_id=request_id,
        )
        return SmsSendResult(
            sent=result.sent,
            suppressed=result.suppressed,
            reason=result.reason,
            provider_message_id=result.message_id,
            segments=result.segments,
        )

    def parse_status(self, params: Mapping[str, str]) -> DeliveryStatus | None:
        return None
