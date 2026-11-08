"""Deterministisk, liten norsk intensjonsparser for prototype-CLI.

Dette er IKKE en full NLP-parser (se docs/nlp/ for den grundige
evalueringen). Den dekker de to demo-spørsmålene og nærliggende varianter,
uten LLM og uten tilfeldighet. Alt som ikke gjenkjennes gir UNKNOWN - vi
gjetter ikke.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Intent:
    raw: str
    kind: str  # "DEPARTURES" | "TRIP" | "UNKNOWN"
    from_text: str = ""
    to_text: str = ""
    line_code: str = ""
    time_text: str = ""
    target_datetime: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def is_departures(self) -> bool:
        return self.kind == "DEPARTURES"

    @property
    def is_trip(self) -> bool:
        return self.kind == "TRIP"


_WEEKDAYS = {
    "mandag": 0,
    "tirsdag": 1,
    "onsdag": 2,
    "torsdag": 3,
    "fredag": 4,
    "lørdag": 5,
    "lordag": 5,
    "søndag": 6,
    "sondag": 6,
}

_LINE_RE = re.compile(r"(?:buss(?:en)?|linje)\s*(?:nr\.?\s*)?(\d{1,3}[a-z]?)", re.IGNORECASE)
_BARE_NUMBER_RE = re.compile(r"\b(\d{1,3})\b")
_TRIP_RE = re.compile(
    r"(?:hvordan\s+(?:kommer|reiser|går)\s+jeg\s+)?fra\s+(?P<from>.+?)\s+til\s+(?P<to>.+)$",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(r"kl(?:okka|okken)?\.?\s*(\d{1,2})(?:[:.](\d{2}))?", re.IGNORECASE)
_RELATIVE_HALF_HOUR_RE = re.compile(r"om\s+(?:en\s+)?halvtime", re.IGNORECASE)


def _strip_place_noise(text: str) -> str:
    """Fjern tidsuttrykk og fyllord fra en stedstekst."""
    out = text.strip(" ?.!,")
    patterns = [
        r"\bi\s+morgen\b",
        r"\bi\s+morra\b",
        r"\bi\s+dag\b",
        r"\bidag\b",
        r"\bi\s+kveld\b",
        r"\bnå\b",
        r"\bnaa\b",
        r"\bsenere\b",
        r"\bseinere\b",
        r"kl(?:okka|okken)?\.?\s*\d{1,2}(?:[:.]\d{2})?",
        r"\bpå\s+(?:mandag|tirsdag|onsdag|torsdag|fredag|lørdag|lordag|søndag|sondag)\b",
        r"\bom\s+(?:en\s+)?halvtime\b",
    ]
    for pattern in patterns:
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip(" ,")
    return out


def _parse_time(text: str, now: datetime) -> tuple[str, str, list[str]]:
    """Returner (target_datetime_iso, time_text, notes)."""
    notes: list[str] = []
    lower = text.lower()
    base_date = now
    day_note = ""

    if re.search(r"\bi\s+morgen\b|\bi\s+morra\b", lower):
        base_date = now + timedelta(days=1)
        day_note = "i morgen"
    elif re.search(r"\bi\s+dag\b|\bidag\b", lower):
        day_note = "i dag"
    else:
        weekday_match = re.search(
            r"\bpå\s+(mandag|tirsdag|onsdag|torsdag|fredag|lørdag|lordag|søndag|sondag)\b", lower
        )
        if weekday_match:
            wanted = _WEEKDAYS[weekday_match.group(1)]
            days_ahead = (wanted - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            base_date = now + timedelta(days=days_ahead)
            day_note = weekday_match.group(1)

    clock_match = _CLOCK_RE.search(lower)
    if clock_match:
        hour = int(clock_match.group(1))
        minute = int(clock_match.group(2) or 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            notes.append(f"ugyldig klokkeslett {clock_match.group(0)!r} - bruker nå")
        else:
            candidate = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if not day_note and candidate < now:
                candidate += timedelta(days=1)
                notes.append("klokkeslettet er passert i dag - tolket som i morgen")
            return candidate.isoformat(), clock_match.group(0).strip(), notes

    if _RELATIVE_HALF_HOUR_RE.search(lower):
        candidate = now + timedelta(minutes=30)
        return candidate.isoformat(), "om en halvtime", notes

    if day_note:
        # Ingen klokketid: bruk samme klokkeslett som nå på valgt dag.
        candidate = base_date
        return candidate.isoformat(), day_note, notes

    notes.append("ingen tidsuttrykk - bruker nå")
    return now.isoformat(), "nå", notes


def interpret(text: str, now: datetime | None = None) -> Intent:
    raw = (text or "").strip()
    now = now or datetime.now().astimezone()
    if not raw:
        return Intent(raw=raw, kind="UNKNOWN", notes=["tom melding"])

    lower = raw.lower()

    trip_match = _TRIP_RE.search(lower)
    if trip_match:
        from_text = _strip_place_noise(trip_match.group("from"))
        to_text = _strip_place_noise(trip_match.group("to"))
        target, time_text, notes = _parse_time(raw, now)
        return Intent(
            raw=raw,
            kind="TRIP",
            from_text=from_text,
            to_text=to_text,
            time_text=time_text,
            target_datetime=target,
            notes=notes,
        )

    departures_markers = [
        "når går",
        "når kommer",
        "når kjem",
        "avgang",
        "går buss",
        "går det buss",
        "neste buss",
    ]
    if any(marker in lower for marker in departures_markers):
        line_match = _LINE_RE.search(raw)
        line_code = line_match.group(1) if line_match else ""
        if not line_code:
            bare = _BARE_NUMBER_RE.search(_strip_place_noise(raw))
            if bare:
                line_code = bare.group(1)
        from_text = ""
        from_match = re.search(r"\bfra\s+(.+)$", lower, re.IGNORECASE)
        if from_match:
            from_text = _strip_place_noise(from_match.group(1))
        else:
            # "Når går buss 22?" uten sted - la kalleren be om sted.
            from_text = ""
        target, time_text, notes = _parse_time(raw, now)
        if not from_text and not line_code:
            notes.append("mangler holdeplass og linje")
            return Intent(raw=raw, kind="UNKNOWN", notes=notes)
        if not from_text:
            notes.append("mangler holdeplass")
        return Intent(
            raw=raw,
            kind="DEPARTURES",
            from_text=from_text,
            line_code=line_code,
            time_text=time_text,
            target_datetime=target,
            notes=notes,
        )

    return Intent(raw=raw, kind="UNKNOWN", notes=["intensjon ikke gjenkjent"])
