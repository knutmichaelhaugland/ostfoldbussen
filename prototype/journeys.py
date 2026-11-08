"""Reisesøk (trip) med ettervalidering av overganger/gange og scope-vakt.

Ettervalidering (krav i oppgave 4):
- overgang = neste transit-beins starttid - forrige transit-beins sluttid.
  Sammenlignes med konfigurerbar minimumsovergang (`transfer_slack_s`).
- gangavstand/-tid = sum av bein med mode == "foot"; sammenlignes med
  konfigurerbare maksgrenser (sum og per bein). API-et kan ikke tvinge
  gangavstand, saa dette MAA gjores etterpaa.
- scope-vakt: alle mellomliggende transit-holdeplasser (unntatt start og maal)
  maa ha countyId == KVE:TopographicPlace:31. Reise som forlater Ostfold via
  mellombytte FLAGGES - den skjules ikke og tillates ikke automatisk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import config

TRIP_QUERY = """
query(
  $from: String!
  $to: String!
  $dateTime: DateTime!
  $numTripPatterns: Int!
  $transferSlack: Int
  $searchWindow: Int
) {
  trip(
    from: {place: $from}
    to: {place: $to}
    dateTime: $dateTime
    numTripPatterns: $numTripPatterns
    transferSlack: $transferSlack
    searchWindow: $searchWindow
  ) {
    tripPatterns {
      aimedStartTime
      expectedStartTime
      aimedEndTime
      expectedEndTime
      duration
      walkTime
      waitingTime
      distance
      streetDistance
      legs {
        mode
        transportSubmode
        duration
        distance
        realtime
        aimedStartTime
        expectedStartTime
        aimedEndTime
        expectedEndTime
        line { id publicCode name transportMode }
        fromPlace {
          name
          latitude
          longitude
          quay { id publicCode stopPlace { id name } }
        }
        toPlace {
          name
          latitude
          longitude
          quay { id publicCode stopPlace { id name } }
        }
        situations { id severity summary { value language } }
      }
    }
    routingErrors { code description }
  }
}
"""

FOOT_MODES = {"foot"}
NON_TRANSIT_MODES = {"foot", "bicycle", "scooter", "car", "car_pooling", "car_pickup"}
TRANSIT_MODES = {"bus", "rail", "tram", "metro", "water", "coach", "cableway", "funicular", "air"}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class StopRef:
    stop_place_id: str | None
    quay_id: str | None
    name: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class Leg:
    mode: str
    transport_submode: str
    duration_s: int
    distance_m: float
    realtime: bool
    aimed_start: str
    expected_start: str
    aimed_end: str
    expected_end: str
    line_id: str
    line_public_code: str
    line_name: str
    line_transport_mode: str
    from_ref: StopRef
    to_ref: StopRef
    situations: list[str] = field(default_factory=list)

    @property
    def is_foot(self) -> bool:
        return self.mode in FOOT_MODES

    @property
    def is_transit(self) -> bool:
        return self.mode in TRANSIT_MODES

    @property
    def start_dt(self) -> datetime | None:
        return _dt(self.expected_start or self.aimed_start)

    @property
    def end_dt(self) -> datetime | None:
        return _dt(self.expected_end or self.aimed_end)


@dataclass
class Transfer:
    at_stop_id: str | None
    at_stop_name: str
    from_line: str
    to_line: str
    arrival_time: str
    departure_time: str
    slack_s: int  # nesteTransitStart - forrigeTransitSlutt
    minimum_s: int
    is_short: bool  # under minimum (klassifiserende)
    is_warn_only: bool  # mellom minimum og advarselsgrense
    walk_m: float = 0.0


@dataclass
class Itinerary:
    index: int
    expected_start: str
    expected_end: str
    aimed_start: str
    aimed_end: str
    duration_s: int
    walk_time_s: int
    waiting_time_s: int
    distance_m: float
    street_distance_m: float
    legs: list[Leg]
    partial_errors: list = field(default_factory=list)

    @property
    def transit_legs(self) -> list[Leg]:
        return [leg for leg in self.legs if leg.is_transit]

    @property
    def foot_legs(self) -> list[Leg]:
        return [leg for leg in self.legs if leg.is_foot]

    @property
    def has_realtime(self) -> bool:
        return any(leg.realtime for leg in self.transit_legs)

    @property
    def start_dt(self) -> datetime | None:
        return _dt(self.expected_start or self.aimed_start)

    @property
    def end_dt(self) -> datetime | None:
        return _dt(self.expected_end or self.aimed_end)


@dataclass
class Assessment:
    transfers: list[Transfer] = field(default_factory=list)
    walk_total_m: float = 0.0
    walk_legs_m: list[float] = field(default_factory=list)
    walk_total_s: int = 0
    violations: list[str] = field(default_factory=list)
    scope: "ScopeReport | None" = None

    @property
    def is_suitable(self) -> bool:
        return not self.violations and self.scope is not None and self.scope.ok

    @property
    def classification(self) -> str:
        # Scope-vakt er et SEPARAT flagg (skal ikke skjules/tillates automatisk),
        # ikke en egnethetsbryt. Klassifiseringen dekker bare overgang/gange.
        if not self.violations:
            return "EGNET"
        return "UEGNET"


@dataclass
class ScopeReport:
    status: str  # "OK" | "FLAGG" | "UKJENT"
    counties: dict = field(default_factory=dict)
    outside: list[dict] = field(default_factory=list)  # {stop_place_id, name, county_id, role}
    transit_stop_ids: list[str] = field(default_factory=list)
    intermediate_stop_ids: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    @property
    def flagged(self) -> bool:
        return self.status in ("FLAGG", "UKJENT")


@dataclass
class TripSearchResult:
    from_place_id: str
    to_place_id: str
    date_time: str
    transfer_slack_s: int
    itineraries: list[Itinerary] = field(default_factory=list)
    assessments: dict = field(default_factory=dict)  # index -> Assessment
    routing_errors: list = field(default_factory=list)
    partial_errors: list = field(default_factory=list)
    status: str = "OK"  # "OK" | "INGEN_FORSLAG" | "RUTING_FEIL"

    @property
    def has_patterns(self) -> bool:
        return bool(self.itineraries)


@dataclass
class Selection:
    itinerary: Itinerary | None
    assessment: Assessment | None
    reason: str


def _stop_ref(place: dict | None) -> StopRef:
    place = place or {}
    quay = place.get("quay") or {}
    stop = quay.get("stopPlace") or {}
    return StopRef(
        stop_place_id=stop.get("id"),
        quay_id=quay.get("id"),
        name=str(place.get("name") or stop.get("name") or ""),
        latitude=place.get("latitude"),
        longitude=place.get("longitude"),
    )


def _summary_texts(situations) -> list[str]:
    out: list[str] = []
    for sit in situations or []:
        for item in sit.get("summary") or []:
            value = (item or {}).get("value")
            if value:
                out.append(str(value))
                break
    return out


def parse_legs(raw_legs) -> list[Leg]:
    legs: list[Leg] = []
    for raw in raw_legs or []:
        line = raw.get("line") or {}
        legs.append(
            Leg(
                mode=str(raw.get("mode") or ""),
                transport_submode=str(raw.get("transportSubmode") or ""),
                duration_s=int(raw.get("duration") or 0),
                distance_m=float(raw.get("distance") or 0.0),
                realtime=bool(raw.get("realtime")),
                aimed_start=str(raw.get("aimedStartTime") or ""),
                expected_start=str(raw.get("expectedStartTime") or ""),
                aimed_end=str(raw.get("aimedEndTime") or ""),
                expected_end=str(raw.get("expectedEndTime") or ""),
                line_id=str(line.get("id") or ""),
                line_public_code=str(line.get("publicCode") or ""),
                line_name=str(line.get("name") or ""),
                line_transport_mode=str(line.get("transportMode") or ""),
                from_ref=_stop_ref(raw.get("fromPlace")),
                to_ref=_stop_ref(raw.get("toPlace")),
                situations=_summary_texts(raw.get("situations")),
            )
        )
    return legs


def parse_itineraries(raw_patterns) -> list[Itinerary]:
    out: list[Itinerary] = []
    for index, raw in enumerate(raw_patterns or []):
        out.append(
            Itinerary(
                index=index,
                expected_start=str(raw.get("expectedStartTime") or ""),
                expected_end=str(raw.get("expectedEndTime") or ""),
                aimed_start=str(raw.get("aimedStartTime") or ""),
                aimed_end=str(raw.get("aimedEndTime") or ""),
                duration_s=int(raw.get("duration") or 0),
                walk_time_s=int(raw.get("walkTime") or 0),
                waiting_time_s=int(raw.get("waitingTime") or 0),
                distance_m=float(raw.get("distance") or 0.0),
                street_distance_m=float(raw.get("streetDistance") or 0.0),
                legs=parse_legs(raw.get("legs")),
            )
        )
    return out


def build_transfers(itinerary: Itinerary, minimum_s: int, warn_below_s: int) -> list[Transfer]:
    """Beregn alle bytter: nesteTransitStart - forrigeTransitSlutt."""
    transfers: list[Transfer] = []
    transit = itinerary.transit_legs
    for prev, nxt in zip(transit, transit[1:]):
        prev_end = prev.end_dt
        next_start = nxt.start_dt
        if prev_end is None or next_start is None:
            continue
        slack = int((next_start - prev_end).total_seconds())
        transfers.append(
            Transfer(
                at_stop_id=prev.to_ref.stop_place_id or nxt.from_ref.stop_place_id,
                at_stop_name=prev.to_ref.name or nxt.from_ref.name,
                from_line=prev.line_public_code,
                to_line=nxt.line_public_code,
                arrival_time=prev.expected_end or prev.aimed_end,
                departure_time=nxt.expected_start or nxt.aimed_start,
                slack_s=slack,
                minimum_s=minimum_s,
                is_short=slack < minimum_s,
                is_warn_only=(slack >= minimum_s) and (slack < warn_below_s),
            )
        )
    return transfers


def assess_itinerary(
    itinerary: Itinerary, thresholds: config.Thresholds, resolver=None
) -> Assessment:
    assessment = Assessment()
    minimum_s = (
        thresholds.minimum_transfer_s
        if thresholds.minimum_transfer_s is not None
        else thresholds.transfer_slack_s
    )
    assessment.transfers = build_transfers(
        itinerary, minimum_s, thresholds.warn_transfer_below_s
    )
    expected_transfers = max(0, len(itinerary.transit_legs) - 1)
    if len(assessment.transfers) < expected_transfers:
        assessment.violations.append("UKJENT_BYTTE:manglende tidspunkt")
    for transfer in assessment.transfers:
        if transfer.is_short:
            assessment.violations.append(
                f"KORT_BYTTE:{transfer.at_stop_name or '?'}:{transfer.slack_s}s<{transfer.minimum_s}s"
            )
    foot = itinerary.foot_legs
    assessment.walk_total_m = round(sum(leg.distance_m for leg in foot), 1)
    assessment.walk_legs_m = [round(leg.distance_m, 1) for leg in foot]
    assessment.walk_total_s = sum(leg.duration_s for leg in foot)
    if thresholds.max_walk_m is not None and assessment.walk_total_m > thresholds.max_walk_m:
        assessment.violations.append(
            f"MYE_GANGE:{assessment.walk_total_m:.0f}m>{thresholds.max_walk_m:.0f}m"
        )
    if thresholds.max_walk_leg_m is not None and any(
        distance > thresholds.max_walk_leg_m for distance in assessment.walk_legs_m
    ):
        assessment.violations.append(
            f"MYE_GANGE_BEIN:{max(assessment.walk_legs_m, default=0):.0f}m>{thresholds.max_walk_leg_m:.0f}m"
        )
    if thresholds.max_walk_time_s is not None and assessment.walk_total_s > thresholds.max_walk_time_s:
        assessment.violations.append(
            f"MYE_GANGTID:{assessment.walk_total_s}s>{thresholds.max_walk_time_s}s"
        )
    if not itinerary.transit_legs:
        assessment.violations.append("INGEN_KOLLEKTIVBEIN")
    assessment.scope = check_scope(itinerary, resolver)
    return assessment


def check_scope(itinerary: Itinerary, resolver) -> ScopeReport:
    """Scope-vakt: mellomliggende transit-holdeplasser maa ligge i Østfold.

    Start (foerste transit-beins fromPlace) og maal (siste transit-beins
    toPlace) er unntatt. Alt annet er mellombyttepunkt og maa ha countyId 31.
    Returnerer status FLAGG ved brudd - reisen skjules ikke, men merkes.
    """
    transit = itinerary.transit_legs
    if not transit:
        return ScopeReport(status="OK")
    endpoints: list[tuple[str, str]] = []  # (stop_place_id, rolle)
    for leg in transit:
        if leg.from_ref.stop_place_id:
            endpoints.append((leg.from_ref.stop_place_id, "mellom"))
        if leg.to_ref.stop_place_id:
            endpoints.append((leg.to_ref.stop_place_id, "mellom"))
    # Foerste avgang og siste ankomst er start/maal, ikke mellombytte.
    if endpoints:
        endpoints[0] = (endpoints[0][0], "start")
        endpoints[-1] = (endpoints[-1][0], "maal")

    ids: list[str] = []
    for stop_id, _role in endpoints:
        if stop_id not in ids:
            ids.append(stop_id)
    # Mellombyttepunkter = alle forekomster unntatt foerste (start) og siste (maal).
    seen: set[str] = set()
    intermediate_unique: list[str] = []
    for sid, role in endpoints[1:-1]:
        if role == "mellom" and sid not in seen:
            seen.add(sid)
            intermediate_unique.append(sid)

    report = ScopeReport(
        status="OK",
        transit_stop_ids=ids,
        intermediate_stop_ids=intermediate_unique,
    )
    if resolver is None:
        report.status = "UKJENT"
        report.error = "ingen geocoder-resolver tilgjengelig"
        return report
    try:
        counties = resolver.counties_of(ids)
    except Exception as exc:  # nettverksfeil skal ikke skjule reisen
        report.status = "UKJENT"
        report.error = f"geocoder-feil: {exc}"
        return report

    report.counties = counties
    names = {sid: _name_for_stop(itinerary, sid) for sid in ids}
    for sid in intermediate_unique:
        county = counties.get(sid)
        if county != config.OSTFOLD_COUNTY_ID:
            report.outside.append(
                {
                    "stop_place_id": sid,
                    "name": names.get(sid) or sid,
                    "county_id": county,
                    "role": "mellombytte",
                }
            )
    if report.outside:
        report.status = "FLAGG"
    return report


def _name_for_stop(itinerary: Itinerary, stop_place_id: str) -> str:
    for leg in itinerary.transit_legs:
        for ref in (leg.from_ref, leg.to_ref):
            if ref.stop_place_id == stop_place_id:
                return ref.name
    return stop_place_id


def assess_all(itineraries: list[Itinerary], thresholds: config.Thresholds, resolver=None) -> dict:
    return {it.index: assess_itinerary(it, thresholds, resolver) for it in itineraries}


def select_itinerary(
    itineraries: list[Itinerary], assessments: dict
) -> Selection:
    """Deterministisk valg: egnet uten scope-flagg > egnet med flagg > foerste."""
    if not itineraries:
        return Selection(None, None, "ingen forslag")
    for it in itineraries:
        a = assessments[it.index]
        if a.classification == "EGNET" and not a.scope.flagged:
            return Selection(it, a, "egnet")
    for it in itineraries:
        a = assessments[it.index]
        if a.classification == "EGNET":
            return Selection(it, a, "egnet, men scope-vakt flagget")
    first = itineraries[0]
    return Selection(first, assessments[first.index], "ingen egnet reise - viser foerste forslag")


def search_trips(
    client,
    from_place_id: str,
    to_place_id: str,
    date_time: str,
    thresholds: config.Thresholds | None = None,
    resolver=None,
) -> TripSearchResult:
    thresholds = thresholds or config.Thresholds()
    variables = {
        "from": from_place_id,
        "to": to_place_id,
        "dateTime": date_time,
        "numTripPatterns": int(thresholds.num_trip_patterns),
        "transferSlack": int(thresholds.transfer_slack_s),
    }
    if thresholds.search_window_minutes is not None:
        variables["searchWindow"] = int(thresholds.search_window_minutes)
    data = client.graphql(TRIP_QUERY, variables=variables)
    trip = data.get("trip")
    result = TripSearchResult(
        from_place_id=from_place_id,
        to_place_id=to_place_id,
        date_time=date_time,
        transfer_slack_s=int(thresholds.transfer_slack_s),
        partial_errors=list(getattr(client, "partial_errors", []) or []),
    )
    if trip is None:
        result.status = "INGEN_FORSLAG"
        return result
    result.routing_errors = list(trip.get("routingErrors") or [])
    result.itineraries = parse_itineraries(trip.get("tripPatterns"))
    if result.routing_errors:
        result.status = "RUTING_FEIL"
    elif not result.itineraries:
        result.status = "INGEN_FORSLAG"
    result.assessments = assess_all(result.itineraries, thresholds, resolver)
    return result
