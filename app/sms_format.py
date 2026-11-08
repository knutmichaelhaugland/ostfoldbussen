"""Dato-bevisst SMS-formatering.

Prototype-formatene viser bare klokkeslett. Et svar kl. 22:22 med neste avgang
05:04 kan derfor leses som «i dag». Denne modulen legger en deterministisk
datomerking foran tidene:

- «i dag» når avgangen er samme kalenderdag som nå,
- «i morgen» når den er neste dag,
- «i overmorgen» for dagen etter,
- kort norsk dato («lør. 8. nov.») for øvrige dager.

Regler:
- Er alle viste avganger samme dag, merkes de én gang: «i morgen: 05:04 …».
- Er de på ulike dager, merkes hver avgang: «i dag 23:45 …, i morgen 00:15 …».
- Reise-SMS merkes ved første kollektivbein: «i morgen 08:39 linje 22 …».

Ingen tilfeldighet; all tekst saniteres til GSM-7. prototype/ er ikke endret.
"""

from __future__ import annotations

from datetime import date, datetime

from prototype import formatting as proto_formatting

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


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _short_date(day: date) -> str:
    return f"{_WEEKDAYS_NO[day.weekday()]} {day.day}. {_MONTHS_NO[day.month - 1]}"


def date_label(iso: str | None, today: date, tz=None) -> str:
    """Returner deterministisk datomerking for en ISO-tid, eller ''.

    `tz` (typisk Europe/Oslo fra request-tidspunktet) brukes til å normalisere
    tider som måtte komme med annen offset, slik at dagsgrensen følger samme
    tidssone som «i dag»-referansen.
    """
    moment = _parse(iso)
    if moment is None:
        return ""
    if tz is not None and moment.tzinfo is not None:
        moment = moment.astimezone(tz)
    delta = (moment.date() - today).days
    if delta == 0:
        return "i dag"
    if delta == 1:
        return "i morgen"
    if delta == 2:
        return "i overmorgen"
    return _short_date(moment.date())


def format_departures_sms(stop_dep, now: datetime) -> tuple[str, list[str]]:
    """Dato-bevisst SMS-utkast for avganger. Returnerer (tekst, datomerker)."""
    if stop_dep is None:
        return proto_formatting.to_gsm7_text("Fant ingen holdeplass. Kilde: Entur"), []

    today = now.date()
    stop_name = stop_dep.stop_name or "holdeplassen"
    line_prefix = f"linje {stop_dep.line_filter}" if stop_dep.line_filter else "avganger"

    if not stop_dep.departures:
        text = f"{stop_name} {line_prefix}: ingen avganger i vinduet."
        text += " Kilde: Entur"
        return proto_formatting.to_gsm7_text(text), []

    shown = stop_dep.departures[: proto_formatting.MAX_SMS_DEPARTURES]
    labels = [
        date_label(departure.departure_time, today, tz=now.tzinfo) for departure in shown
    ]
    entries = [proto_formatting.departure_line(departure) for departure in shown]

    if labels and len(set(labels)) == 1 and labels[0]:
        text = f"{stop_name} {line_prefix}: {labels[0]}: " + ", ".join(entries) + "."
    else:
        labelled = [
            f"{label} {entry}" if label else entry for label, entry in zip(labels, entries)
        ]
        text = f"{stop_name} {line_prefix}: " + ", ".join(labelled) + "."

    if stop_dep.timetable_only:
        text += " Rutetider (ikke sanntid)."
    elif stop_dep.realtime_count > 0:
        text += " Sanntid der den finnes."
    text += " Kilde: Entur"
    return proto_formatting.to_gsm7_text(text), labels


def format_trip_sms(itinerary, assessment, now: datetime) -> tuple[str, str]:
    """Dato-bevisst reise-SMS. Returnerer (tekst, datomerke)."""
    if itinerary is None:
        return "", ""
    base = proto_formatting.format_trip_sms(itinerary, assessment)
    transit = itinerary.transit_legs
    if not transit:
        return base, ""
    first = transit[0]
    start_iso = first.expected_start or first.aimed_start
    label = date_label(start_iso, now.date(), tz=now.tzinfo)
    if not label:
        return base, ""
    clock = proto_formatting.format_clock(start_iso)
    marker = f"{clock} linje"
    if marker in base:
        base = base.replace(marker, f"{label} {marker}", 1)
    else:
        # Ukjent format: legg merkingen foran hele teksten (fortsatt ærlig).
        base = f"{label}: {base}"
    return base, label
