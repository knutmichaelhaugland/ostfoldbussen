"""Konfigurasjon for den isolerte, lokale Entur-kjernen (prototype).

Alle Entur-kall må sende en unik ET-Client-Name. Se docs/ og
docs/ for verifiserte kontrakter. Denne modulen er ren stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Entur-endepunkter (verifisert i docs/journey-planner, docs/geocoder-transit) ---

ET_CLIENT_NAME = "ostfoldbussen-selfhosted"

JOURNEY_PLANNER_URL = "https://api.entur.io/journey-planner/v3/graphql"
GEOCODER_AUTOCOMPLETE_URL = "https://api.entur.io/geocoder/v3/autocomplete"
GEOCODER_PLACE_URL = "https://api.entur.io/geocoder/v3/place"

# Østfold fylke. Brukes som hardt filter i Geocoder (`counties=`) og som
# ettervalidering (`address.countyId`). bbox brukes IKKE som fylkesfilter.
OSTFOLD_COUNTY_ID = "KVE:TopographicPlace:31"
OSTFOLD_COUNTY_NAME = "Østfold"
GEOCODER_LAYERS = "stopPlace"

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3


@dataclass(frozen=True)
class Thresholds:
    """Terskler for prototypekjøring.

    INGEN av disse er vedtatt som produktvalg. Standardverdiene er valgt slik at
    de er *entydig dokumenterte*:

    - `transfer_slack_s=120` er Enturs dokumenterte API-standard (se
      docs/ENTUR-API-AUDIT.md og docs/journey-suitability/). Det er altså
      ikke en produktbeslutning, men API-ets eget minimum.
    - `warn_transfer_below_s=300` er kun en ADVARSEL i SMS-teksten, ikke et
      filter, og er merket som prototypeverdi (ikke vedtatt).
    - `max_walk_m` / `max_walk_time_s` er None (= ingen hard grense) som
      standard. Terskelmatrisen (prototype/threshold_matrix.py) setter dem
      eksplisitt til 250/500 m.
    """

    transfer_slack_s: int = 120  # API-default; hard minimumsovergang i Raptor
    minimum_transfer_s: int | None = None  # ettervalideringsminimum; None => transfer_slack_s
    warn_transfer_below_s: int = 300  # ADVARSEL, ikke filter (prototypeverdi)
    max_walk_m: float | None = None  # sum gangavstand per reise (hard grense)
    max_walk_leg_m: float | None = None  # per-bein gangavstand (hard grense)
    max_walk_time_s: int | None = None  # sum gangtid per reise (hard grense)
    warn_walk_above_m: float = 500.0  # ADVARSEL, ikke filter (prototypeverdi)
    num_trip_patterns: int = 10
    search_window_minutes: int | None = None  # None => API-default
    departures_window: int = 20  # antall estimatedCalls vi ber om


# Alias-tabell: bevisste PRODUKTVALG, ikke Entur-data.
# «Moss sentrum» finnes ikke som StopPlace (verifisert i GEO-10: kun
# destinationDisplay.frontText paa linje 22). Vi mapper derfor uttrykket til
# Moss bussterminal. Hvert alias er merket med kilde slik at CLI/rapport kan
# skille produktvalg fra API-oppslag.
ALIASES: dict[str, dict] = {
    "moss sentrum": {
        "stop_place_id": "NSR:StopPlace:2900",
        "name": "Moss bussterminal",
        "source": "produktvalg-alias",
        "note": "«Moss sentrum» finnes ikke som StopPlace; bruker Moss bussterminal.",
    },
    "moss sentrum byen": {
        "stop_place_id": "NSR:StopPlace:2900",
        "name": "Moss bussterminal",
        "source": "produktvalg-alias",
        "note": "«Moss sentrum» finnes ikke som StopPlace; bruker Moss bussterminal.",
    },
    "byen": {
        "stop_place_id": "NSR:StopPlace:2900",
        "name": "Moss bussterminal",
        "source": "produktvalg-alias",
        "note": "«byen» tolkes som Moss sentrum; bruker Moss bussterminal.",
    },
}


def normalize_place_text(text: str) -> str:
    """Deterministisk normalisering for alias-oppslag (ikke for API-søk)."""
    t = (text or "").strip().lower()
    t = t.replace("æ", "æ").replace("ø", "ø").replace("å", "å")
    t = t.replace("-", " ").replace("_", " ")
    for ch in ".,;:!?\"'«»()":
        t = t.replace(ch, " ")
    return " ".join(t.split())
