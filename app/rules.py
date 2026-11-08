"""App-spesifikk tolkning: prototype.intent.interpret + trygg oppfølgingshåndtering.

prototype/ eies av prototype og endres ikke. Denne adapteren legger til:
- «Når går bussen?» uten sted/linje regnes som avgangerspørsmål (ikke UNKNOWN),
  slik at konversasjonskontekst kan fylle inn sted. Spørsmål med «til X» men
  uten «fra» forblir UNKNOWN (retningsspørsmål støttes ikke).
- Ingen LLM-kall; LLM er egen adapter i app/llm.py.
"""

from __future__ import annotations

from datetime import datetime

import re

from prototype import intent as proto_intent
from prototype.intent import Intent

DEPARTURE_MARKERS = (
    "når går",
    "når kommer",
    "når kjem",
    "avgang",
    "går buss",
    "går det buss",
    "neste buss",
)


_BARE_TRIP_RX = re.compile(
    r"^\s*(?P<a>[A-Za-zÆØÅæøå][A-Za-zÆØÅæøå0-9 .\-]{1,39}?)\s+til\s+"
    r"(?P<b>[A-Za-zÆØÅæøå][A-Za-zÆØÅæøå0-9 .\-]{1,39}?)\s*[?.!]*\s*$"
)
_TRIP_WORDS = ("når", "går", "kommer", "kjører", "hvordan", "jeg", "skal", "vil", "buss",
               "avgang", "neste", "siste", "tilbake")


def rules_interpret(message: str, now: datetime | None = None) -> Intent:
    intent = proto_intent.interpret(message, now=now)
    # R/RE-linjer (R21, R22, RE20) må bevares; prototype fanger bare tall.
    line_match = re.search(r"\b(RE?\d{1,3})\b", message or "", re.IGNORECASE)
    if line_match and intent.kind != "UNKNOWN":
        code = line_match.group(1).upper()
        if not intent.line_code or intent.line_code.isdigit():
            from prototype.intent import Intent as _Intent
            return _Intent(
                raw=message,
                kind=intent.kind,
                from_text=intent.from_text,
                to_text=intent.to_text,
                line_code=code,
                time_text=intent.time_text,
                target_datetime=intent.target_datetime,
                notes=list(intent.notes) + ["R/RE-linje bevart"],
            )

    if intent.kind != "UNKNOWN":
        return intent
    # «R21 fra Askim stasjon» / «RE20 fra Råde stasjon»
    bare_line = re.match(r"^\s*(RE?\d{1,3})\s+fra\s+(.+?)\s*[?.!]*$", message or "",
                         re.IGNORECASE)
    if bare_line:
        from datetime import timezone

        moment = now or datetime.now(timezone.utc)
        return Intent(
            raw=message,
            kind="DEPARTURES",
            from_text=bare_line.group(2).strip(),
            line_code=bare_line.group(1).upper(),
            time_text="nå",
            target_datetime=moment.isoformat(),
            notes=["R/RE-linje uten spørreord"],
        )

    # «Skredderåsen til Refsnes» (mandatets eksempel) uten spørreord/verb.
    match = _BARE_TRIP_RX.match(message or "")
    if match and not any(word in (message or "").lower() for word in _TRIP_WORDS):
        from datetime import timezone

        moment = now or datetime.now(timezone.utc)
        return Intent(
            raw=message,
            kind="TRIP",
            from_text=match.group("a").strip(),
            to_text=match.group("b").strip(),
            time_text="nå",
            target_datetime=moment.isoformat(),
            notes=["mønster «A til B» uten spørreord"],
        )
    lower = (message or "").lower()
    if not any(marker in lower for marker in DEPARTURE_MARKERS):
        return intent
    if " til " in lower:
        # «Når går bussen til Refsnes?» - retning, ikke holdeplass. Ikke gjett.
        return intent
    if "fra" in lower:
        return intent
    notes = list(intent.notes)
    notes.append("avgangerspørsmål uten sted - kan fylles fra kontekst")
    return Intent(raw=message, kind="DEPARTURES", notes=notes)
