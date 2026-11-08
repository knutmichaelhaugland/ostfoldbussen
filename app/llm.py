"""LLM-adapter bak provider-nøytralt interface (OpenAI-kompatibelt /v1).

LLM_ENABLED=false => aldri nettverkskall. Når aktivert sendes ALDRI
telefonnummer eller pseudonym til modellen; kun meldingsteksten. Svaret må
validere mot et strengt schema; ved feil faller vi tilbake til RULES.

STATUS: adapteren er UTESTET mot ekte provider (ingen nøkkel i denne fasen).
Enhetstestene dekker disabled, ugyldig JSON, timeout og fallback.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .logging_setup import log
from .http_util import open_no_redirect

ALLOWED_KINDS = {"DEPARTURES", "JOURNEY", "TRIP", "LAST_DEPARTURE",
                 "OUT_OF_SCOPE", "REJECT", "THANKS", "UNKNOWN"}
APP_KIND = {"DEPARTURES": "DEPARTURES", "LAST_DEPARTURE": "DEPARTURES",
            "TRIP": "TRIP", "JOURNEY": "TRIP"}

SYSTEM_PROMPT = (
    "Du tolker korte norske SMS-spørsmål om kollektivtrafikk i Østfold. "
    "Svar KUN med JSON. Felter: kind, origin_text, destination_text, line_number, "
    "time_text, clarification_needed.\n"
    "kind: DEPARTURES (avganger fra én holdeplass), JOURNEY (reise fra A til B), "
    "LAST_DEPARTURE (siste avgang), OUT_OF_SCOPE, REJECT, THANKS, UNKNOWN.\n"
    "VIKTIG: både avreisested og reisemål => JOURNEY, også når det spørres om avgangstid.\n"
    "origin_text = avreisested (for DEPARTURES: holdeplassen, også ved «til X»). "
    "destination_text = reisemål, kun JOURNEY. line_number = linje uten «buss». "
    "time_text = tidsuttrykk ordrett. Ikke finn på steder eller tider.\n"
    "Eksempel: «Når går buss 22 fra Skredderåsen?» -> {\"kind\":\"DEPARTURES\","
    "\"origin_text\":\"Skredderåsen\",\"line_number\":\"22\",\"clarification_needed\":false}\n"
    "Eksempel: «Fra Ørje til Refsnes» -> {\"kind\":\"JOURNEY\",\"origin_text\":\"Ørje\","
    "\"destination_text\":\"Refsnes\",\"clarification_needed\":false}\n"
    "Eksempel: «Jeg skal til Refsnes» -> {\"kind\":\"JOURNEY\",\"origin_text\":\"\","
    "\"destination_text\":\"Refsnes\",\"clarification_needed\":true}\n"
    "origin_text/destination_text skal KUN inneholde stedsnavn — aldri pronomen, verb "
    "eller spørreord som «jeg», «skal», «til», «fra», «buss»."
)


_STOPWORDS = {"jeg", "meg", "vi", "oss", "du", "deg", "han", "hun", "det", "den",
              "skal", "vil", "reise", "til", "fra", "buss", "bussen", "går", "gå",
              "når", "hvor", "hvordan", "neste", "siste", "herfra", "dit", "hjem"}


def _clean_place(value: str) -> str:
    """Fjern pronomen/verb som modellen kan ha plassert i stedsfeltet."""
    words = [w for w in value.strip().split() if w.lower().strip(",.?!") not in _STOPWORDS]
    cleaned = " ".join(words).strip(" ,.")
    return cleaned if cleaned.lower() not in _STOPWORDS else ""


@dataclass
class LlmResult:
    ok: bool
    data: dict | None
    error: str = ""


class LlmInterpreter:
    def __init__(self, config, http_post=None, db=None):
        self.config = config
        self._http_post = http_post or self._default_post
        self.db = db
        self.last_error = ""
        self.calls = 0

    def _count(self, kind: str) -> None:
        if self.db is not None:
            try:
                self.db.increment_counter(kind)
            except Exception:
                pass

    @property
    def enabled(self) -> bool:
        return bool(self.config.llm_enabled)

    def interpret(self, message: str) -> LlmResult:
        if not self.enabled:
            return LlmResult(ok=False, data=None, error="disabled")
        if not isinstance(message, str) or not message.strip():
            return LlmResult(ok=False, data=None, error="empty_input")
        if len(message) > self.config.llm_max_input_chars:
            self.last_error = "input_too_long"
            self._count("llm_failures")
            return LlmResult(ok=False, data=None, error="input_too_long")
        self.calls += 1
        self._count("llm_attempts")
        try:
            payload = self._http_post(message)
        except Exception as exc:  # timeout, HTTP-feil, JSON-feil
            self.last_error = type(exc).__name__
            self._count("llm_failures")
            log("llm_call_failed", error=self.last_error)
            return LlmResult(ok=False, data=None, error=self.last_error)
        data = self._validate(payload)
        if data is None:
            self.last_error = "schema_invalid"
            self._count("llm_failures")
            log("llm_invalid_schema")
            return LlmResult(ok=False, data=None, error="schema_invalid")
        usage = payload.get("usage") if isinstance(payload, dict) else {}
        if isinstance(usage, dict):
            self._increment_amount("llm_input_tokens", int(usage.get("prompt_tokens", 0) or 0))
            self._increment_amount("llm_output_tokens", int(usage.get("completion_tokens", 0) or 0))
        self._count("llm_success")
        return LlmResult(ok=True, data=data)

    def _increment_amount(self, kind: str, amount: int) -> None:
        if amount and self.db is not None:
            try:
                self.db.increment_counter(kind, amount)
            except Exception:
                pass

    def _validate(self, payload) -> dict | None:
        if not isinstance(payload, dict):
            return None
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        if not isinstance(content, str):
            return None
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        kind = parsed.get("kind")
        if kind not in ALLOWED_KINDS:
            return None
        cleaned = {"kind": APP_KIND.get(kind, "UNKNOWN")}
        pairs = {
            "from_text": ("from_text", "origin_text"),
            "to_text": ("to_text", "destination_text"),
            "line_code": ("line_code", "line_number"),
            "time_text": ("time_text",),
        }
        for target, sources in pairs.items():
            value = ""
            for source in sources:
                candidate = parsed.get(source)
                if isinstance(candidate, str):
                    value = candidate
                    break
            if len(value) > 120:
                return None
            cleaned[target] = _clean_place(value) if target in {"from_text", "to_text"} else value.strip()
        return cleaned


    def _default_post(self, message: str) -> dict:
        base = self.config.llm_base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        payload = {
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": getattr(self.config, "llm_max_output_tokens", 400),
        }
        if self.config.llm_model.startswith(("qwen3.6-", "qwen3.8-")):
            effort = getattr(self.config, "llm_reasoning_effort", "none")
            if effort and effort != "absent":
                payload["reasoning_effort"] = effort
        # urllib krever bytes; tidligere kunne denne grenen sende str.
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.llm_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ostfoldbussen/1.0",
            },
            method="POST",
        )
        with open_no_redirect(request, timeout=self.config.llm_timeout_s) as response:
            return json.loads(response.read().decode("utf-8", "replace"))


class Interpreter:
    """RULES først; LLM kun når RULES ikke forstår og LLM er aktivert."""

    def __init__(self, rules_interpret, llm: LlmInterpreter, clock=None):
        self.rules_interpret = rules_interpret
        self.llm = llm
        self.clock = clock

    def interpret(self, message: str, context: dict | None = None):
        intent = self.rules_interpret(message)
        if intent.kind != "UNKNOWN":
            return intent, "rules"
        # Ren oppfølging: bruk lagret kontekst før vi vurderer LLM (sparer kall og tid).
        if context and context.get("kind") in {"DEPARTURES", "TRIP"}:
            from prototype.intent import Intent

            return Intent(
                raw=message,
                kind=context["kind"],
                from_text=context.get("from_text", "") or "",
                to_text=context.get("to_text", "") or "",
                line_code=context.get("line_code", "") or "",
                time_text="",
                target_datetime="",
                notes=["kontekst fra forrige melding"],
            ), "context"
        if not self.llm.enabled:
            return intent, "rules"
        result = self.llm.interpret(message)
        if not result.ok or result.data is None:
            log("llm_fallback_rules", reason=result.error)
            return intent, "rules_fallback"
        data = result.data
        from prototype.intent import Intent  # importeres lokalt: prototype eies av prototype

        fallback_intent = Intent(
            raw=message,
            kind=data["kind"],
            from_text=data.get("from_text", ""),
            to_text=data.get("to_text", ""),
            line_code=data.get("line_code", ""),
            time_text=data.get("time_text", ""),
            target_datetime="",
        )
        return fallback_intent, "llm"
