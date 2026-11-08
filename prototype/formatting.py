"""Deterministisk norsk formatering: detaljrapport + SMS-utkast.

Ingen tilfeldighet, ingen locale-avhengighet. SMS-tekst saniteres til
GSM-7-vennlige tegn (æ/ø/å er GSM-7; «» – · … er det ikke).
"""

from __future__ import annotations

from datetime import datetime

from . import config
from .departures import StopDepartures
from .journeys import Assessment, Itinerary

MAX_SMS_DEPARTURES = 3

_WEEKDAYS_NO = ["man.", "tir.", "ons.", "tor.", "fre.", "lør.", "søn."]
_MONTHS_NO = [
    "jan.",
    "feb.",
    "mars",
    "apr.",
    "mai",
    "juni",
    "juli",
    "aug.",
    "sep.",
    "okt.",
    "nov.",
    "des.",
]

# Tegn som ikke finnes i GSM-7 og som vi erstatter deterministisk.
_GSM_REPLACEMENTS = {
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u00ab": '"',  # «
    "\u00bb": '"',  # »
    "\u2019": "'",  # ’
    "\u2018": "'",  # ‘
    "\u201c": '"',
    "\u201d": '"',
    "\u00b7": "-",  # ·
    "\u2026": "...",  # …
    "\u00a0": " ",  # hardt mellomrom
    "\u2022": "-",  # •
    "\u2192": "->",  # →
    "\u00b0": " grader",
    "\u20ac": "EUR",
}


def to_gsm7_text(text: str) -> str:
    """Saniter teksten slik at den holder seg i GSM-7 der det er mulig."""
    out = []
    for ch in text or "":
        if ch in _GSM_REPLACEMENTS:
            out.append(_GSM_REPLACEMENTS[ch])
        else:
            out.append(ch)
    return "".join(out)


def format_clock(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return iso[11:16] if len(iso) >= 16 else iso


def format_date_no(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{_WEEKDAYS_NO[dt.weekday()]} {dt.day}. {_MONTHS_NO[dt.month - 1]} {dt.year}"


def format_minutes(seconds: int) -> str:
    return f"{max(0, int(seconds)) // 60} min"


def format_delay(departure) -> str:
    delay = departure.delay_seconds
    if departure.realtime and delay >= 60:
        return f" (+{delay // 60} min)"
    return ""


# ---------------------------------------------------------------------------
# Avganger
# ---------------------------------------------------------------------------
def departure_line(departure) -> str:
    """Kort linje+retning+tid, f.eks. '20:51 mot Kambo'."""
    return f"{format_clock(departure.departure_time)}{format_delay(departure)} mot {departure.direction or '?'}"


def departure_warnings(stop_dep: StopDepartures) -> list[str]:
    warnings: list[str] = []
    if stop_dep is None:
        return ["fant ikke holdeplassen"]
    if stop_dep.all_departures_count == 0:
        warnings.append("ingen avganger i vinduet (kan bety utenfor driftstid)")
    if stop_dep.line_filter and not stop_dep.departures and stop_dep.all_departures_count:
        warnings.append(f"ingen avganger for linje {stop_dep.line_filter} i vinduet")
    if stop_dep.departures and stop_dep.timetable_only:
        warnings.append("rutetider - sanntid mangler for denne holdeplassen/linjen")
    elif stop_dep.departures and stop_dep.realtime_count < len(stop_dep.departures):
        warnings.append("blandet sanntid: noen avganger er rutetider")
    for departure in stop_dep.departures[:MAX_SMS_DEPARTURES]:
        if departure.cancellation:
            warnings.append(
                f"{format_clock(departure.departure_time)} linje {departure.line_public_code} er innstilt"
            )
        if departure.prediction_inaccurate:
            warnings.append(
                f"{format_clock(departure.departure_time)} linje {departure.line_public_code}: usikker prognose"
            )
        for text in departure.situations[:1]:
            warnings.append(f"avvik: {text}")
    return warnings


def format_departures_sms(stop_dep: StopDepartures) -> str:
    """Deterministisk SMS-utkast for avganger."""
    if stop_dep is None:
        return to_gsm7_text("Fant ingen holdeplass. Kilde: Entur")
    stop_name = stop_dep.stop_name or "holdeplassen"
    line_prefix = f"linje {stop_dep.line_filter}" if stop_dep.line_filter else "avganger"
    if not stop_dep.departures:
        text = f"{stop_name} {line_prefix}: ingen avganger i vinduet."
    else:
        shown = stop_dep.departures[:MAX_SMS_DEPARTURES]
        parts = [departure_line(dep) for dep in shown]
        text = f"{stop_name} {line_prefix}: " + ", ".join(parts) + "."
        if stop_dep.timetable_only:
            text += " Rutetider (ikke sanntid)."
        elif stop_dep.realtime_count > 0:
            text += " Sanntid der den finnes."
    text += " Kilde: Entur"
    return to_gsm7_text(text)


# ---------------------------------------------------------------------------
# Reiser
# ---------------------------------------------------------------------------
def _leg_ref_name(leg) -> str:
    return leg.to_ref.name or leg.from_ref.name or "?"


def itinerary_steps(itinerary: Itinerary) -> list[str]:
    """Detaljerte steg for rapport (ikke SMS), kronologisk."""
    steps: list[str] = []
    transit = itinerary.transit_legs
    if not transit:
        return ["ingen kollektivbein"]
    previous_transit = None
    for leg in itinerary.legs:
        if leg.is_transit:
            if previous_transit is not None:
                gap_s = int((leg.start_dt - previous_transit.end_dt).total_seconds()) if (
                    leg.start_dt and previous_transit.end_dt
                ) else 0
                steps.append(
                    f"bytte {previous_transit.to_ref.name} {format_minutes(gap_s)} "
                    f"({format_clock(previous_transit.expected_end)} -> {format_clock(leg.expected_start)})"
                )
            steps.append(
                f"linje {leg.line_public_code} mot {_leg_ref_name(leg)} "
                f"{format_clock(leg.expected_start)}-{format_clock(leg.expected_end)}"
                f"{' [sanntid]' if leg.realtime else ' [rutetider]'}"
            )
            previous_transit = leg
        elif leg.is_foot and leg.distance_m > 0:
            steps.append(
                f"gå {leg.distance_m:.0f} m ({format_minutes(leg.duration_s)}) "
                f"fra {leg.from_ref.name} til {leg.to_ref.name}"
            )
    last = transit[-1]
    steps.append(f"framme {format_clock(last.expected_end)} ved {last.to_ref.name}")
    return steps


def itinerary_warnings(itinerary: Itinerary, assessment: Assessment, thresholds=None) -> list[str]:
    warnings: list[str] = []
    if assessment is None:
        return warnings
    for transfer in assessment.transfers:
        if transfer.is_short:
            warnings.append(
                f"kort bytte {format_minutes(transfer.slack_s)} på {transfer.at_stop_name or '?'} "
                f"(minimum {format_minutes(transfer.minimum_s)})"
            )
        elif transfer.is_warn_only:
            warnings.append(
                f"stramt bytte {format_minutes(transfer.slack_s)} på {transfer.at_stop_name or '?'}"
            )
    warn_above = getattr(thresholds, "warn_walk_above_m", None) if thresholds is not None else None
    if assessment.walk_total_m > 0:
        text = f"gange {assessment.walk_total_m:.0f} m ({format_minutes(assessment.walk_total_s)})"
        if warn_above is not None and assessment.walk_total_m > warn_above:
            text += f" - over advarselsgrensen {warn_above:.0f} m"
        warnings.append(text)
    for violation in assessment.violations:
        if violation.startswith("MYE_GANGE"):
            warnings.append(f"mye gange: {violation.split(':', 1)[-1]}")
    scope = assessment.scope
    if scope is not None and scope.flagged:
        if scope.status == "FLAGG":
            names = ", ".join(
                f"{item.get('name', '?')} ({item.get('county_id') or 'ukjent fylke'})"
                for item in scope.outside
            )
            warnings.append(f"SCOPE-BRUD: reisen forlater Østfold via {names} - FLAGGET")
        else:
            warnings.append(f"scope-vakt UVERIFISERT: {scope.error or 'kunne ikke verifisere fylke'}")
    if not itinerary.has_realtime and not itinerary.transit_legs:
        warnings.append("ingen kollektivdata")
    return warnings


def format_trip_sms(itinerary: Itinerary, assessment: Assessment) -> str:
    """Deterministisk SMS-utkast for en valgt reise."""
    if itinerary is None:
        return to_gsm7_text("Fant ingen reise. Kilde: Entur")
    transit = itinerary.transit_legs
    origin = itinerary.legs[0].from_ref.name if itinerary.legs else "?"
    destination = itinerary.legs[-1].to_ref.name if itinerary.legs else "?"
    duration = format_minutes(itinerary.duration_s)

    if not transit:
        text = f"{origin} til {destination}: reisen fant ingen kollektivbein."
    else:
        parts: list[str] = []
        previous_transit = None
        transit_seen = 0
        for leg in itinerary.legs:
            if leg.is_transit:
                transfer_index = transit_seen - 1
                if previous_transit is None:
                    parts.append(
                        f"{format_clock(leg.expected_start)} linje {leg.line_public_code} "
                        f"mot {_leg_ref_name(leg)}"
                    )
                else:
                    gap_s = int((leg.start_dt - previous_transit.end_dt).total_seconds()) if (
                        leg.start_dt and previous_transit.end_dt
                    ) else 0
                    transfer_text = (
                        f"bytte {previous_transit.to_ref.name} {format_minutes(gap_s)}"
                    )
                    minimum_s = 0
                    if assessment is not None and transfer_index < len(assessment.transfers):
                        minimum_s = assessment.transfers[transfer_index].minimum_s
                    if gap_s < minimum_s:
                        transfer_text += " (kort!)"
                    parts.append(transfer_text)
                    parts.append(
                        f"{format_clock(leg.expected_start)} linje {leg.line_public_code} "
                        f"mot {_leg_ref_name(leg)}"
                    )
                previous_transit = leg
                transit_seen += 1
            elif leg.is_foot and leg.distance_m > 0:
                parts.append(f"gå {leg.distance_m:.0f} m")
        parts.append(f"framme {format_clock(transit[-1].expected_end)}")
        text = f"{origin} til {destination}: " + ", ".join(parts) + f". {duration}."
        if any(leg.realtime for leg in transit):
            text += " Sanntid der den finnes."
        else:
            text += " Rutetider."
    if assessment is not None and assessment.scope is not None and assessment.scope.flagged:
        if assessment.scope.status == "FLAGG":
            names = ", ".join(
                str(item.get("name", "?")) for item in assessment.scope.outside
            ) or "ukjent sted"
            text += f" Obs: reisen går via {names} utenfor Østfold."
        else:
            text += " Obs: fylke kunne ikke verifiseres."
    text += " Kilde: Entur"
    return to_gsm7_text(text)


# ---------------------------------------------------------------------------
# Detaljrapport (ikke SMS)
# ---------------------------------------------------------------------------
_INTENT_LABELS = {"DEPARTURES": "AVGANGER", "TRIP": "REISE", "UNKNOWN": "UKJENT"}


def _get(obj, name, default=""):
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def intent_block(intent) -> list[str]:
    kind = _get(intent, "kind", "UNKNOWN")
    lines = [f"Tolket intensjon: {_INTENT_LABELS.get(kind, kind)} ({kind})"]
    for key, label in (
        ("from_text", "fra-tekst"),
        ("to_text", "til-tekst"),
        ("line_code", "linje"),
        ("time_text", "tidsuttrykk"),
    ):
        value = _get(intent, key, "")
        if value:
            lines.append(f"  {label}: {value!r}" if key != "line_code" else f"  {label}: {value}")
    target = _get(intent, "target_datetime", "")
    if target:
        lines.append(f"  tidspunkt: {target}")
    for note in _get(intent, "notes", []) or []:
        lines.append(f"  merknad: {note}")
    return lines
