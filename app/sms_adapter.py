"""Lite, leverandøruavhengig SMS-adaptergrensesnitt.

Kjernen eier reiselogikk, database og kostnadsreservasjon. Adapteren eier kun
leverandørspesifikk webhookverifisering, sending og statusparsing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class InboundSms:
    provider: str
    request_id: str
    sender: str
    message: str


@dataclass(frozen=True)
class InboundVerification:
    accepted: bool
    reason: str = ""
    inbound: InboundSms | None = None


@dataclass(frozen=True)
class SmsSendResult:
    sent: bool
    suppressed: bool
    reason: str
    provider_message_id: str | None = None
    segments: int = 0


@dataclass(frozen=True)
class DeliveryStatus:
    provider_message_id: str
    status: str


@runtime_checkable
class SmsAdapter(Protocol):
    name: str

    def verify_inbound(self, headers: Mapping[str, str], body: bytes) -> InboundVerification:
        ...

    def claim_inbound(self, inbound: InboundSms) -> bool:
        ...

    def mark_inbound(self, inbound: InboundSms, status: str) -> None:
        ...

    def send(self, to_number: str, body: str, *, pseudonym: str | None,
             idempotency_key: str, request_id: int | None = None) -> SmsSendResult:
        ...

    def parse_status(self, params: Mapping[str, str]) -> DeliveryStatus | None:
        ...
