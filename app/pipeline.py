"""Kjerne-pipeline: intent -> geocoder -> avganger/reiser -> formatering -> SMS.

Gjenbruker prototype/ (uendret prototypekontrakt) og legger på:
- resultattyper VALID_SUITABLE / VALID_UNSUITABLE / NO_JOURNEY / TECHNICAL_ERROR
- scope-policy (flagg / kreve innenfor Østfold)
- full trace + latency
- pseudonymisert lagring (aldri rå melding/telefonnummer)
- konversasjonskontekst med TTL 30 min
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from prototype import config as proto_config
from prototype import departures as proto_departures
from prototype import formatting as proto_formatting
from prototype import intent as proto_intent
from prototype import journeys as proto_journeys
from prototype import sms as proto_sms
from prototype.entur_client import EnturError
from prototype.geocoder import PlaceResolver

from .db import utc_now
from .entur_gateway import AppEnturClient
from .logging_setup import elapsed_ms, log
from .place_logic import Candidate, choose_place, format_clarification
from .llm import Interpreter, LlmInterpreter
from .bineric_llm import BinericLlm
from .rules import rules_interpret
from . import sms_format

RESULT_TYPES = {"VALID_SUITABLE", "VALID_UNSUITABLE", "NO_JOURNEY", "TECHNICAL_ERROR"}

SUPPORTED_QUESTION_KINDS = {"DEPARTURES", "TRIP"}


@dataclass
class PipelineDeps:
    client: object
    resolver: PlaceResolver
    thresholds: object

    @classmethod
    def default(cls, config) -> "PipelineDeps":
        client = AppEnturClient(config)
        return cls(
            client=client,
            resolver=PlaceResolver(client),
            thresholds=config.thresholds(),
        )


def message_hash(message: str, key: str = "") -> str:
    """Returner HMAC-SHA256, eller tom streng når ingen egen nøkkel er satt.

    Usaltet SHA-256 er bevisst fjernet: korte SMS-spørsmål er gjettbare.
    Hash lagres ikke når nøkkelen mangler.
    """
    if not key:
        return ""
    data = (message or "").strip().encode("utf-8")
    return hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()


def pseudonymize(salt: str, identifier: str) -> str:
    return hmac.new(
        (salt or "").encode("utf-8"), (identifier or "").encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _place_trace(resolution) -> dict | None:
    if resolution is None:
        return None
    hit = resolution.hit
    return {
        "query": resolution.query,
        "found": resolution.found,
        "id": hit.id if hit else None,
        "name": hit.name if hit else None,
        "layer": hit.layer if hit else None,
        "county_id": hit.county_id if hit else None,
        "source": hit.source if hit else None,
        "alias_used": resolution.alias_used,
        "alias_note": resolution.alias_note,
        "ambiguous": resolution.ambiguous,
        "candidates": [
            {"id": c.id, "name": c.name, "county_id": c.county_id} for c in resolution.candidates
        ],
        "rejected": [
            {"id": r.id, "name": r.name, "layer": r.layer, "county_id": r.county_id, "reason": r.reason}
            for r in resolution.rejected
        ],
    }


def _itinerary_trace(itinerary, assessment) -> dict:
    scope = assessment.scope
    return {
        "index": itinerary.index,
        "start": itinerary.expected_start,
        "end": itinerary.expected_end,
        "duration_s": itinerary.duration_s,
        "realtime": itinerary.has_realtime,
        "classification": assessment.classification,
        "recommended": False,
        "violations": list(assessment.violations),
        "walk_total_m": assessment.walk_total_m,
        "walk_total_s": assessment.walk_total_s,
        "transfers": [
            {
                "at": transfer.at_stop_name,
                "slack_s": transfer.slack_s,
                "minimum_s": transfer.minimum_s,
                "is_short": transfer.is_short,
                "is_warn_only": transfer.is_warn_only,
            }
            for transfer in assessment.transfers
        ],
        "scope": {
            "status": scope.status if scope else "UKJENT",
            "outside": scope.outside if scope else [],
        },
        "legs": [
            {
                "mode": leg.mode,
                "line": leg.line_public_code,
                "from": leg.from_ref.name,
                "to": leg.to_ref.name,
                "start": leg.expected_start,
                "end": leg.expected_end,
                "realtime": leg.realtime,
            }
            for leg in itinerary.legs
        ],
    }


def _segment_trace(text: str) -> dict:
    info = proto_sms.count_segments(text)
    return {
        "encoding": info.encoding,
        "segments": info.segments,
        "units": info.units,
        "per_segment": info.per_segment,
        "chars": info.chars,
        "gsm7_safe": info.gsm7_safe,
    }


def _safe_sms(text: str) -> str:
    return proto_formatting.to_gsm7_text(text)


class Pipeline:
    def __init__(self, config, db, deps: PipelineDeps | None = None, interpreter=None, now_fn=None):
        self.config = config
        self.db = db
        self.deps = deps or PipelineDeps.default(config)
        self.llm = (BinericLlm(config, db) if config.bineric_enabled
                    else LlmInterpreter(config, db=db))
        self.interpreter = interpreter or Interpreter(rules_interpret, self.llm)
        tz = ZoneInfo(config.app_timezone)
        self._now = now_fn or (lambda: datetime.now(tz))

    # -- offentlig -------------------------------------------------------
    def run(
        self,
        message: str,
        *,
        pseudonym: str | None = None,
        channel: str = "api",
        conversation_key: str | None = None,
    ) -> dict:
        started = time.perf_counter()
        trace = None
        try:
            trace = self._run_inner(message, pseudonym, channel, conversation_key)
        except EnturError as exc:
            log("pipeline_entur_error", error=type(exc).__name__)
            trace = self._base_trace(message, channel, "TECHNICAL_ERROR", "entur_error")
            trace["error_category"] = type(exc).__name__
            trace["warnings"] = ["Entur er utilgjengelig akkurat nå. Prøv igjen om litt."]
            trace["sms"] = self._error_sms()
        except Exception as exc:  # pragma: no cover - siste skanse
            log("pipeline_internal_error", error=type(exc).__name__)
            trace = self._base_trace(message, channel, "TECHNICAL_ERROR", "internal_error")
            trace["error_category"] = type(exc).__name__
            trace["warnings"] = ["Intern feil. Prøv igjen senere."]
            trace["sms"] = self._error_sms()

        latency = elapsed_ms(started)
        trace["latency_ms"] = latency
        trace["build_sha"] = self.config.build_sha
        trace["timestamp"] = datetime.now(ZoneInfo("UTC")).isoformat()
        trace["_message_hash"] = message_hash(message, self.config.message_hash_key)

        try:
            request_id = self.db.record_request(
                created_at=trace["timestamp"],
                sender_pseudonym=pseudonym,
                message_hash=trace["_message_hash"],
                intent=trace["intent"].get("kind"),
                result_type=trace["result_type"],
                status="ok" if trace["result_type"] != "TECHNICAL_ERROR" else "error",
                latency_ms=latency,
                build_sha=self.config.build_sha,
                error_category=trace.get("error_category"),
                channel=channel,
            )
            trace["request_id"] = request_id
            self.db.increment_counter("requests")
            if trace["result_type"] == "TECHNICAL_ERROR":
                self.db.increment_counter("errors")
            try:
                self._queue_error_review(trace, request_id, pseudonym)
            except Exception as exc:  # køen skal aldri skjule svaret
                log("error_review_queue_failed", error=type(exc).__name__)
            if trace.get("interpretation_source") == "llm":
                self.db.increment_counter("llm_calls")
            elif trace.get("interpretation_source") == "rules_fallback":
                self.db.increment_counter("llm_fallbacks")
            if conversation_key and trace["intent"].get("kind") in SUPPORTED_QUESTION_KINDS:
                self.db.save_conversation(
                    conversation_key,
                    {
                        "kind": trace["intent"].get("kind"),
                        "from_text": trace["intent"].get("from_text", ""),
                        "to_text": trace["intent"].get("to_text", ""),
                        "line_code": trace["intent"].get("line_code", ""),
                        "updated_at": trace["timestamp"],
                    },
                    self.config.conversation_ttl_minutes,
                )
        except Exception as exc:  # DB-feil skal ikke skjule svaret, men logges
            log("pipeline_db_error", error=type(exc).__name__)
            trace["request_id"] = None

        log(
            "pipeline_run",
            request_id=trace.get("request_id"),
            channel=channel,
            intent=trace["intent"].get("kind"),
            result_type=trace["result_type"],
            latency_ms=latency,
            error_category=trace.get("error_category"),
        )
        trace.pop("_message_hash", None)
        return trace

    def _increment(self, kind: str) -> None:
        try:
            self.db.increment_counter(kind)
        except Exception:
            pass

    # -- oppklaring og tvetydighet (mandat §7) ----------------------------
    _TIL_RX = re.compile(r"\btil\s+(\S.*)$", re.IGNORECASE)

    def _clarification(self, message: str, intent) -> dict | None:
        """Be om ett kort oppklarende spørsmål når noe nødvendig mangler."""
        text = message or ""
        lower = text.lower()
        has_til = bool(self._TIL_RX.search(text))
        has_fra = "fra" in lower
        if intent.kind not in SUPPORTED_QUESTION_KINDS:
            if has_til and not has_fra:
                match = self._TIL_RX.search(text)
                destination = (match.group(1) or "").strip(" ?.!") if match else ""
                return {
                    "reason": "missing_origin",
                    "text": f"Hvor reiser du fra? F.eks. «Fra Skredderåsen til {destination or 'Refsnes'}».",
                }
            if has_fra and not has_til:
                return {
                    "reason": "missing_destination",
                    "text": "Hvor vil du reise? F.eks. «Skredderåsen til Refsnes».",
                }
            return None
        if (intent.kind == "DEPARTURES" and intent.from_text
                and not intent.line_code
                and lower.startswith("fra ")
                and not any(marker in lower for marker in
                            ("når", "avgang", "går", "buss", "kommer", "neste"))):
            return {
                "reason": "missing_destination",
                "text": "Hvor vil du reise? F.eks. «Skredderåsen til Refsnes».",
            }
        if intent.kind == "DEPARTURES" and not intent.from_text:
            return {
                "reason": "missing_place",
                "text": "Hvilken holdeplass gjelder det? F.eks. «Når går bussen fra Skredderåsen?».",
            }
        if intent.kind == "TRIP":
            if not intent.from_text and not intent.to_text:
                return {
                    "reason": "missing_place",
                    "text": "Hvor reiser du fra, og hvor vil du reise? F.eks. «Fra Skredderåsen til Refsnes».",
                }
            if not intent.from_text:
                return {
                    "reason": "missing_origin",
                    "text": "Hvor reiser du fra? F.eks. «Fra Skredderåsen til Refsnes».",
                }
            if not intent.to_text:
                return {
                    "reason": "missing_destination",
                    "text": "Hvor vil du reise? F.eks. «Skredderåsen til Refsnes».",
                }
        return None

    def _place_gate(self, resolution) -> "Decision | None":
        """Bekreftelsesport: returner Decision eller None hvis ikke mulig."""
        if resolution is None:
            return None
        candidates = [
            Candidate(id=c.id, name=c.name, locality=getattr(c, "locality", "") or "")
            for c in getattr(resolution, "candidates", [])
            if getattr(c, "id", "")
        ]
        if not candidates:
            return None
        return choose_place(resolution.query, candidates)

    def _gate_clarification(self, decision) -> str | None:
        if decision is not None and decision.decision == "clarify":
            return format_clarification("", decision)
        return None

    def _apply_context_time_shift(self, intent, message: str, now):
        lowered = (message or "").lower()
        from datetime import timedelta

        if any(marker in lowered for marker in ("time senere", "timer senere", "senere")):
            intent.target_datetime = (now + timedelta(hours=1)).isoformat()
            intent.notes.append("tid forskjøvet +1 time fra kontekst")
        elif "i morgen" in lowered:
            intent.target_datetime = (now + timedelta(days=1)).isoformat()
            intent.notes.append("tid forskjøvet +1 dag fra kontekst")
        return intent

    # -- feilgjennomgang (mandat §10) ------------------------------------
    FAILURE_REASONS = {
        "intent_not_understood": "interpretation",
        "place_not_found": "geocoding",
        "entur_null_stop_place": "entur",
        "routing_error": "journey",
        "no_journey": "journey",
        "no_suitable_journey": "suitability",
        "scope_rejected": "scope",
        "entur_error": "entur",
        "internal_error": "internal",
    }

    def _queue_error_review(self, trace: dict, request_id, pseudonym) -> None:
        result_type = trace.get("result_type")
        reason = trace.get("result_reason") or ""
        if result_type == "TECHNICAL_ERROR":
            stage = self.FAILURE_REASONS.get(reason, "internal")
        elif result_type == "NO_JOURNEY" and reason in self.FAILURE_REASONS:
            stage = self.FAILURE_REASONS[reason]
        else:
            return
        place_ids = []
        for key in ("from", "to"):
            place = (trace.get("places") or {}).get(key) or {}
            if place.get("id"):
                place_ids.append(str(place["id"]))
        category = trace.get("error_category") or reason or "unknown"
        self.db.add_error_review(
            created_at=trace.get("timestamp") or utc_now(),
            request_id=request_id,
            category=category,
            pseudonym_ref=pseudonym,
            place_ids=place_ids,
            failure_stage=stage,
            build_sha=self.config.build_sha,
        )

    # -- intern ----------------------------------------------------------
    def _base_trace(self, message, channel, result_type, reason) -> dict:
        return {
            "channel": channel,
            "result_type": result_type,
            "result_reason": reason,
            "recommended": False,
            "intent": {
                "kind": "UNKNOWN",
                "from_text": "",
                "to_text": "",
                "line_code": "",
                "time_text": "",
                "target_datetime": "",
                "notes": [],
            },
            "interpretation_source": "rules",
            "places": {"from": None, "to": None},
            "warnings": [],
            "sms": {
                "text": "",
                "segments": _segment_trace(""),
                "outbound_enabled": False,
                "date_marks": [],
            },
            "api": {"operation": None, "call_count": 0, "statuses": []},
            "error_category": None,
        }

    def _error_sms(self) -> dict:
        text = _safe_sms("Beklager, tjenesten er midlertidig utilgjengelig. Prøv igjen om litt.")
        return {
            "text": text,
            "segments": _segment_trace(text),
            "outbound_enabled": self._outbound_enabled(),
            "date_marks": [],
        }

    def _outbound_enabled(self) -> bool:
        return bool(
            self.config.inmobile_outbound_enabled
            and self.config.inmobile_api_key
            and self.config.inmobile_from
        )

    def _run_inner(self, message, pseudonym, channel, conversation_key) -> dict:
        now = self._now()
        context = None
        if conversation_key:
            try:
                context = self.db.load_conversation(conversation_key, now)
            except Exception:
                context = None
        try:
            intent, source = self.interpreter.interpret(message, context=context)
        except TypeError:  # eldre/test-interpreter uten context-parameter
            intent, source = self.interpreter.interpret(message)
        if context:
            intent, source = self._merge_context(intent, source, context, message)
            intent = self._apply_context_time_shift(intent, message, now)

        trace = self._base_trace(message, channel, "NO_JOURNEY", "not_processed")
        trace["interpretation_source"] = source
        trace["intent"] = {
            "kind": intent.kind,
            "from_text": intent.from_text,
            "to_text": intent.to_text,
            "line_code": intent.line_code,
            "time_text": intent.time_text,
            "target_datetime": intent.target_datetime,
            "notes": list(intent.notes),
        }

        clarification = self._clarification(message, intent)
        if clarification is not None:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = clarification["reason"]
            trace["warnings"] = [clarification["text"]]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace

        if intent.kind not in SUPPORTED_QUESTION_KINDS:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "intent_not_understood"
            trace["warnings"] = [
                "Jeg forstod ikke spørsmålet. Skriv f.eks. «Når går buss 22 fra Skredderåsen?» "
                "eller «Hvordan kommer jeg fra Skredderåsen til Refsnes?»."
            ]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace

        from_res = self.deps.resolver.resolve(intent.from_text) if intent.from_text else None
        trace["places"]["from"] = _place_trace(from_res)
        gate = self._place_gate(from_res)
        ambiguous = self._gate_clarification(gate)
        if ambiguous is not None:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "ambiguous_place"
            trace["warnings"] = [ambiguous]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace
        if from_res is None or not from_res.found:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "place_not_found"
            self._increment("geocoder_failures")
            trace["warnings"] = [
                f"Fant ikke stedet «{intent.from_text}» i Østfold. Sjekk skrivemåten."
            ]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace

        if intent.is_departures:
            return self._departures_trace(trace, intent, from_res, now)

        to_res = self.deps.resolver.resolve(intent.to_text) if intent.to_text else None
        trace["places"]["to"] = _place_trace(to_res)
        gate = self._place_gate(to_res)
        ambiguous = self._gate_clarification(gate)
        if ambiguous is not None:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "ambiguous_place"
            trace["warnings"] = [ambiguous]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace
        if to_res is None or not to_res.found:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "place_not_found"
            self._increment("geocoder_failures")
            trace["warnings"] = [
                f"Fant ikke stedet «{intent.to_text}» i Østfold. Sjekk skrivemåten."
            ]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace
        return self._trip_trace(trace, intent, from_res, to_res, now)

    def _departures_trace(self, trace, intent, from_res, now) -> dict:
        client = self.deps.client
        wanted = max(60, self.config.num_trip_patterns * 2) if intent.line_code else 40
        stop_dep = proto_departures.get_departures(
            client,
            from_res.hit.id,
            number_of_departures=wanted,
            line_public_code=intent.line_code or None,
            start_time=intent.target_datetime or None,
        )
        trace["api"] = {
            "operation": "stopPlace.estimatedCalls",
            "call_count": len(getattr(client, "calls", [])),
            "statuses": [c.status for c in getattr(client, "calls", [])],
            "stop_place_id": from_res.hit.id,
            "stop_name": stop_dep.stop_name if stop_dep else None,
            "all_departures_count": stop_dep.all_departures_count if stop_dep else 0,
            "line_filter": intent.line_code or None,
            "matched": len(stop_dep.departures) if stop_dep else 0,
        }
        if stop_dep is None:
            trace["result_type"] = "TECHNICAL_ERROR"
            trace["result_reason"] = "entur_null_stop_place"
            trace["error_category"] = "EnturNullData"
            trace["warnings"] = ["Entur svarte uten holdeplassdata. Prøv igjen."]
            trace["sms"] = self._error_sms()
            return trace
        if stop_dep.partial_errors:
            trace["result_type"] = "TECHNICAL_ERROR"
            trace["result_reason"] = "partial_graphql_errors"
            trace["error_category"] = "EnturPartialData"
            trace["warnings"] = [
                "Entur svarte bare delvis. Avgangsdataene er ikke brukt."
            ]
            trace["sms"] = self._error_sms()
            return trace

        trace["departures"] = [
            {
                "line": dep.line_public_code,
                "direction": dep.direction,
                "aimed": dep.aimed,
                "expected": dep.expected,
                "display_time": dep.departure_time,
                "realtime": dep.realtime,
                "timetable_only": dep.is_timetable_only,
                "delay_s": dep.delay_seconds,
                "cancellation": dep.cancellation,
                "quay_public_code": dep.quay_public_code,
                "situations": list(dep.situations),
            }
            for dep in stop_dep.departures
        ]
        trace["warnings"] = proto_formatting.departure_warnings(stop_dep)
        if not stop_dep.departures:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "no_departures"
        elif all(dep.cancellation for dep in stop_dep.departures):
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "all_cancelled"
            trace["warnings"].append("Alle viste avganger er innstilt.")
        else:
            trace["result_type"] = "VALID_SUITABLE"
            trace["result_reason"] = "departures_found"
            trace["recommended"] = True
        trace["sms"] = self._sms_for_trace(trace, stop_dep=stop_dep, now=now)
        return trace

    def _trip_trace(self, trace, intent, from_res, to_res, now) -> dict:
        client = self.deps.client
        result = proto_journeys.search_trips(
            client,
            from_res.hit.id,
            to_res.hit.id,
            intent.target_datetime or now.isoformat(),
            thresholds=self.deps.thresholds,
            resolver=self.deps.resolver,
        )
        trace["api"] = {
            "operation": "trip",
            "call_count": len(getattr(client, "calls", [])),
            "statuses": [c.status for c in getattr(client, "calls", [])],
            "status": result.status,
            "pattern_count": len(result.itineraries),
            "transfer_slack_s": result.transfer_slack_s,
            "routing_errors": list(result.routing_errors),
        }
        if result.partial_errors:
            trace["result_type"] = "TECHNICAL_ERROR"
            trace["result_reason"] = "partial_graphql_errors"
            trace["error_category"] = "EnturPartialData"
            trace["warnings"] = [
                "Entur svarte bare delvis. Reisedataene er ikke brukt."
            ]
            trace["sms"] = self._error_sms()
            return trace
        if result.status == "RUTING_FEIL":
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "routing_error"
            self._increment("routing_failures")
            trace["warnings"] = [
                "Entur fant ingen rute mellom disse stedene: "
                + "; ".join(
                    f"{err.get('code')}: {err.get('description')}" for err in result.routing_errors
                )
            ]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace
        if not result.itineraries:
            trace["result_type"] = "NO_JOURNEY"
            trace["result_reason"] = "no_journey"
            trace["warnings"] = ["Fant ingen reise i tidsvinduet."]
            trace["sms"] = self._sms_for_trace(trace, now=now)
            return trace

        itineraries = result.itineraries
        assessments = result.assessments

        def scope_ok(it) -> bool:
            scope = assessments[it.index].scope
            return scope is not None and scope.status == "OK"

        in_scope = [it for it in itineraries if scope_ok(it)]
        if self.config.scope_policy == "require_in_scope":
            if not in_scope:
                trace["itineraries"] = [
                    _itinerary_trace(it, assessments[it.index]) for it in itineraries
                ]
                trace["result_type"] = "NO_JOURNEY"
                trace["result_reason"] = "scope_rejected"
                trace["warnings"] = [
                    "Alle forslag forlater Østfold (eller kunne ikke verifiseres). "
                    "Tjenesten svarer bare på reiser i Østfold."
                ]
                trace["sms"] = self._sms_for_trace(trace, now=now)
                return trace
            candidates = in_scope
        else:
            candidates = itineraries

        suitable = [
            it for it in candidates if assessments[it.index].classification == "EGNET" and scope_ok(it)
        ]
        trace["itineraries"] = [
            _itinerary_trace(it, assessments[it.index]) for it in itineraries
        ]
        flagged = [it for it in itineraries if not scope_ok(it)]
        if flagged:
            outside_names = sorted(
                {
                    item["name"]
                    for it in flagged
                    for item in (assessments[it.index].scope.outside if assessments[it.index].scope else [])
                }
            )
            trace["warnings"].append(
                f"{len(flagged)} av {len(itineraries)} forslag forlater Østfold"
                + (f" via {', '.join(outside_names)}" if outside_names else "")
                + " og er ikke anbefalt."
            )

        if suitable:
            selection = proto_journeys.select_itinerary(suitable, assessments)
            itinerary = selection.itinerary
            assessment = assessments[itinerary.index]
            trace["result_type"] = "VALID_SUITABLE"
            trace["result_reason"] = "suitable_journey_found"
            trace["recommended"] = True
            trace["selected"] = {
                "index": itinerary.index,
                "reason": "anbefalt: egnet reise innenfor Østfold",
                "recommended": True,
            }
            trace["warnings"].extend(
                proto_formatting.itinerary_warnings(itinerary, assessment, self.deps.thresholds)
            )
            trace["sms"] = self._sms_for_trace(trace, itinerary=itinerary, assessment=assessment, now=now)
            return trace

        # Fant reise, men ingen egnet -> ALDRI anbefalt.
        fallback = proto_journeys.select_itinerary(itineraries, assessments)
        itinerary = fallback.itinerary or itineraries[0]
        assessment = assessments[itinerary.index]
        trace["result_type"] = "VALID_UNSUITABLE"
        trace["result_reason"] = "no_suitable_journey"
        trace["recommended"] = False
        trace["selected"] = {
            "index": itinerary.index,
            "reason": "IKKE ANBEFALT: ingen egnet reise funnet",
            "recommended": False,
        }
        trace["warnings"].append(
            "Ingen egnet reise funnet. Forslaget under er IKKE anbefalt - det bryter "
            "konfigurerte krav til overgang, gange eller Østfold-scope."
        )
        trace["warnings"].extend(
            proto_formatting.itinerary_warnings(itinerary, assessment, self.deps.thresholds)
        )
        trace["sms"] = self._sms_for_trace(trace, itinerary=itinerary, assessment=assessment, now=now)
        return trace

    # -- SMS-utkast ------------------------------------------------------
    def _sms_for_trace(self, trace, *, itinerary=None, assessment=None, stop_dep=None, now=None) -> dict:
        kind = trace["intent"].get("kind")
        result_type = trace["result_type"]
        now = now or self._now()
        marks: list[str] = []
        if result_type == "TECHNICAL_ERROR":
            return self._error_sms()
        if kind == "DEPARTURES" and stop_dep is not None:
            text, marks = sms_format.format_departures_sms(stop_dep, now)
        elif kind == "TRIP" and itinerary is not None:
            text, mark = sms_format.format_trip_sms(itinerary, assessment, now)
            if mark:
                marks = [mark]
            if result_type == "VALID_UNSUITABLE":
                text = _safe_sms("Ingen egnet reise. Forslaget er IKKE anbefalt: ") + text
        elif result_type == "NO_JOURNEY":
            text = _safe_sms(self._no_journey_sms(trace))
        else:
            text = _safe_sms(self._no_journey_sms(trace))
        return {
            "text": text,
            "segments": _segment_trace(text),
            "outbound_enabled": self._outbound_enabled(),
            "date_marks": marks,
        }

    CLARIFICATION_REASONS = {
        "missing_origin", "missing_destination", "missing_place", "ambiguous_place",
    }

    def _no_journey_sms(self, trace) -> str:
        reason = trace.get("result_reason")
        if reason in self.CLARIFICATION_REASONS:
            warnings = trace.get("warnings") or []
            if warnings:
                return _safe_sms(str(warnings[0]))
        intent = trace["intent"]
        if intent.get("kind") == "DEPARTURES":
            place = (trace.get("places", {}).get("from") or {}).get("name") or intent.get("from_text")
            return f"Fant ingen avganger fra {place}. Prøv igjen senere."
        if intent.get("kind") == "TRIP":
            from_name = (trace.get("places", {}).get("from") or {}).get("name") or intent.get("from_text")
            to_name = (trace.get("places", {}).get("to") or {}).get("name") or intent.get("to_text")
            return f"Fant ingen reise fra {from_name} til {to_name}. Prøv igjen senere."
        return "Fant ingen reise. Skriv f.eks. «Når går buss 22 fra Skredderåsen?»"

    # -- kontekst --------------------------------------------------------
    def _merge_context(self, intent, source, context, message):
        from prototype.intent import Intent

        kind = intent.kind
        from_text = intent.from_text
        to_text = intent.to_text
        line_code = intent.line_code
        if kind == "UNKNOWN" and context.get("kind") in SUPPORTED_QUESTION_KINDS:
            kind = context["kind"]
            source = "context"
        if not from_text and context.get("from_text"):
            from_text = context["from_text"]
            source = "context" if source == "rules" else source
        if not to_text and context.get("to_text"):
            to_text = context["to_text"]
        if not line_code and context.get("line_code"):
            line_code = context["line_code"]
        if (kind, from_text, to_text, line_code) == (
            intent.kind,
            intent.from_text,
            intent.to_text,
            intent.line_code,
        ):
            return intent, source
        return (
            Intent(
                raw=message,
                kind=kind,
                from_text=from_text,
                to_text=to_text,
                line_code=line_code,
                time_text=intent.time_text,
                target_datetime=intent.target_datetime,
                notes=list(intent.notes) + ["kontekst fra forrige melding"],
            ),
            source,
        )
