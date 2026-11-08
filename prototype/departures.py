"""Avganger fra holdeplass (stopPlace.estimatedCalls) med rutetid/sanntid-skille."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

DEPARTURES_QUERY = """
query($stopPlaceId: String!, $numberOfDepartures: Int!, $startTime: DateTime) {
  stopPlace(id: $stopPlaceId) {
    id
    name
    transportMode
    quays { id publicCode name }
    estimatedCalls(numberOfDepartures: $numberOfDepartures, startTime: $startTime) {
      aimedDepartureTime
      expectedDepartureTime
      actualDepartureTime
      realtime
      predictionInaccurate
      cancellation
      quay { id publicCode name }
      destinationDisplay { frontText }
      serviceJourney {
        id
        directionType
        journeyPattern { line { id publicCode name transportMode } }
      }
      situations { id severity summary { value language } }
    }
  }
}
"""


def _pick_summary(values) -> str:
    """Velg norsk tekst deterministisk: nb > no > en > første."""
    texts = []
    for item in values or []:
        if isinstance(item, dict):
            texts.append((str(item.get("language") or ""), str(item.get("value") or "")))
    for lang in ("nb", "no", "nn", "en"):
        for item_lang, value in texts:
            if item_lang == lang and value:
                return value
    for _lang, value in texts:
        if value:
            return value
    return ""


@dataclass
class Departure:
    line_public_code: str
    line_id: str
    line_name: str
    transport_mode: str
    direction: str
    direction_type: str
    aimed: str
    expected: str
    actual: str | None
    realtime: bool
    prediction_inaccurate: bool
    cancellation: bool
    quay_id: str
    quay_public_code: str
    situations: list[str] = field(default_factory=list)

    @property
    def departure_time(self) -> str:
        """Tid som skal vises: expected naar sanntid finnes, ellers aimed."""
        return self.expected or self.aimed

    @property
    def is_timetable_only(self) -> bool:
        """True => svaret bygger paa rutetider (realtime=false)."""
        return not self.realtime

    @property
    def delay_seconds(self) -> int:
        try:
            aim = datetime.fromisoformat(self.aimed)
            exp = datetime.fromisoformat(self.expected)
        except (TypeError, ValueError):
            return 0
        return int((exp - aim).total_seconds())


@dataclass
class StopDepartures:
    stop_place_id: str
    stop_name: str
    transport_modes: list[str]
    quays: list[dict]
    departures: list[Departure]
    line_filter: str | None = None
    all_departures_count: int = 0
    partial_errors: list = field(default_factory=list)

    @property
    def timetable_only(self) -> bool:
        """Alle viste avganger mangler sanntid."""
        return bool(self.departures) and all(d.is_timetable_only for d in self.departures)

    @property
    def realtime_count(self) -> int:
        return sum(1 for d in self.departures if d.realtime)


def _parse_departures(stop: dict) -> list[Departure]:
    out: list[Departure] = []
    for call in stop.get("estimatedCalls") or []:
        sj = call.get("serviceJourney") or {}
        journey_pattern = sj.get("journeyPattern") or {}
        line = journey_pattern.get("line") or {}
        quay = call.get("quay") or {}
        situations = []
        for sit in call.get("situations") or []:
            text = _pick_summary(sit.get("summary"))
            if text:
                situations.append(text)
        out.append(
            Departure(
                line_public_code=str(line.get("publicCode") or ""),
                line_id=str(line.get("id") or ""),
                line_name=str(line.get("name") or ""),
                transport_mode=str(line.get("transportMode") or ""),
                direction=str((call.get("destinationDisplay") or {}).get("frontText") or ""),
                direction_type=str(sj.get("directionType") or ""),
                aimed=str(call.get("aimedDepartureTime") or ""),
                expected=str(call.get("expectedDepartureTime") or ""),
                actual=call.get("actualDepartureTime"),
                realtime=bool(call.get("realtime")),
                prediction_inaccurate=bool(call.get("predictionInaccurate")),
                cancellation=bool(call.get("cancellation")),
                quay_id=str(quay.get("id") or ""),
                quay_public_code=str(quay.get("publicCode") or ""),
                situations=situations,
            )
        )
    return out


def get_departures(
    client,
    stop_place_id: str,
    number_of_departures: int = 20,
    line_public_code: str | None = None,
    start_time: str | None = None,
) -> StopDepartures | None:
    """Hent avganger. Returnerer None naar ukjent StopPlace-ID (data.stopPlace=null)."""
    data = client.graphql(
        DEPARTURES_QUERY,
        variables={
            "stopPlaceId": stop_place_id,
            "numberOfDepartures": int(number_of_departures),
            "startTime": start_time,
        },
    )
    stop = data.get("stopPlace")
    if stop is None:
        return None
    all_departures = _parse_departures(stop)
    departures = all_departures
    if line_public_code:
        wanted = str(line_public_code).strip().upper()
        departures = [d for d in all_departures if d.line_public_code.upper() == wanted]
    return StopDepartures(
        stop_place_id=str(stop.get("id") or stop_place_id),
        stop_name=str(stop.get("name") or ""),
        transport_modes=[str(m) for m in (stop.get("transportMode") or [])],
        quays=list(stop.get("quays") or []),
        departures=departures,
        line_filter=line_public_code,
        all_departures_count=len(all_departures),
        partial_errors=list(getattr(client, "partial_errors", []) or []),
    )
