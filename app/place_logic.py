"""Deterministisk stedsvalg: aldri gjett når stedet er tvetydig.

Ren logikk uten nettverk; kandidater kommer fra Entur Geocoder med fylkesfilter.
Brukes som bekreftelsesport før Journey Planner.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0


@dataclass
class Candidate:
    id: str
    name: str
    locality: str = ""
    lat: float | None = None
    lon: float | None = None


@dataclass
class Decision:
    decision: str  # exact | accept | clarify | not_found
    chosen: Candidate | None = None
    options: list[Candidate] | None = None
    reason: str = ""


def normalize(text: str) -> str:
    text = (text or "").lower().strip()
    for a, b in (("æ", "ae"), ("ø", "o"), ("å", "a"), ("'", ""), ("’", "")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text)


def distance_km(a: Candidate, b: Candidate) -> float | None:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def choose_place(query: str, candidates: list[Candidate], *,
                 context: Candidate | None = None,
                 max_context_km: float = 25.0) -> Decision:
    """Eksakt vinner; ellers avklar hvis flere, aksepter hvis én."""
    candidates = [c for c in candidates if c.id]
    if not candidates:
        return Decision("not_found", reason="ingen kandidater i Østfold")
    wanted = normalize(query)
    exact = [c for c in candidates if normalize(c.name) == wanted]
    if len({c.id for c in exact}) == 1:
        return Decision("exact", chosen=exact[0], reason="eksakt navnetreff")

    # R6: kontekstnærhet kan løse opp både eksakt-navn-kollisjoner og ulike navn
    def nearby(items):
        if context is None:
            return []
        return [c for c in items
                if (d := distance_km(context, c)) is not None and d <= max_context_km]

    if exact:
        within = nearby(exact)
        if len({c.id for c in within}) == 1:
            return Decision("accept", chosen=within[0],
                            reason="eksakt navn, én nær kontekst")
        return Decision("clarify", options=(within or exact)[:3],
                        reason="flere stopp med samme navn")

    if len(candidates) == 1:
        return Decision("accept", chosen=candidates[0], reason="eneste kandidat i Østfold")

    within = nearby(candidates)
    if len({c.id for c in within}) == 1:
        return Decision("accept", chosen=within[0], reason="én kandidat nær kontekst")
    if within:
        return Decision("clarify", options=within[:3], reason="flere kandidater nær kontekst")

    return Decision("clarify", options=candidates[:3], reason="flere ulike kandidater")


def format_clarification(query: str, decision: Decision) -> str:
    names = []
    seen = set()
    for option in decision.options or []:
        label = option.name if not option.locality else f"{option.name} ({option.locality})"
        if label not in seen:
            seen.add(label)
            names.append(label)
    if not names:
        return "Hvilken holdeplass mener du?"
    listed = " eller ".join(names[:3])
    return f"Mente du {listed}? Skriv holdeplassnavnet i meldingen."
