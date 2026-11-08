"""Stedsoppslag i Østfold via Entur Geocoder v3, med hard ettervalidering.

Strategi (verifisert):
- `GET /geocoder/v3/autocomplete?q=...&counties=KVE:TopographicPlace:31&layers=stopPlace&limit=N`
- Ettervalider HVER treff: `properties.layer == "stopPlace"` OG
  `properties.address.countyId == "KVE:TopographicPlace:31"`.
- bbox brukes IKKE som fylkesfilter (lekker: «Oslo S» ga treff i Østfold-bbox).
- Alias-tabellen i config er PRODUKTVALG og merkes som det.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config


@dataclass
class PlaceHit:
    id: str
    name: str
    layer: str
    county_id: str
    county: str
    locality: str
    transport_modes: list[str] = field(default_factory=list)
    stop_place_types: list[str] = field(default_factory=list)
    source: str = "geocoder-autocomplete"
    score_rank: int = 0

    @property
    def is_ostfold(self) -> bool:
        return self.county_id == config.OSTFOLD_COUNTY_ID


@dataclass
class RejectedFeature:
    id: str
    name: str
    layer: str
    county_id: str
    reason: str


@dataclass
class PlaceResolution:
    query: str
    hit: PlaceHit | None
    candidates: list[PlaceHit] = field(default_factory=list)
    rejected: list[RejectedFeature] = field(default_factory=list)
    alias_used: bool = False
    alias_note: str = ""
    ambiguous: bool = False
    raw_county_filter: str = config.OSTFOLD_COUNTY_ID

    @property
    def found(self) -> bool:
        return self.hit is not None


def _feature_to_hit(feature: dict, rank: int, source: str = "geocoder-autocomplete") -> PlaceHit:
    props = feature.get("properties") or {}
    names = props.get("names") or {}
    address = props.get("address") or {}
    return PlaceHit(
        id=str(props.get("id") or ""),
        name=str(names.get("default") or names.get("display") or ""),
        layer=str(props.get("layer") or ""),
        county_id=str(address.get("countyId") or ""),
        county=str(address.get("county") or ""),
        locality=str(address.get("locality") or ""),
        transport_modes=[str(m.get("mode")) for m in (props.get("transportModes") or []) if m],
        stop_place_types=[str(t) for t in (props.get("stopPlaceTypes") or [])],
        source=source,
        score_rank=rank,
    )


def validate_feature(
    feature: dict, rank: int, require_ostfold: bool = True
) -> tuple[PlaceHit | None, RejectedFeature | None]:
    """Ettervalider ett Geocoder-treff. Returnerer (hit, None) eller (None, reject).

    `require_ostfold=False` brukes av scope-vakten: den MAA kunne lese
    countyId for steder UTENFOR Østfold for å kunne flagge dem.
    """
    hit = _feature_to_hit(feature, rank)
    if hit.layer != "stopPlace":
        return None, RejectedFeature(hit.id, hit.name, hit.layer, hit.county_id, "layer!=stopPlace")
    if not hit.id:
        return None, RejectedFeature("", hit.name, hit.layer, hit.county_id, "mangler id")
    if require_ostfold and hit.county_id != config.OSTFOLD_COUNTY_ID:
        return None, RejectedFeature(
            hit.id, hit.name, hit.layer, hit.county_id, "countyId!=KVE:TopographicPlace:31"
        )
    return hit, None


class PlaceResolver:
    def __init__(self, client):
        self.client = client
        self._county_cache: dict[str, str] = {}
        self._place_cache: dict[str, PlaceHit | None] = {}

    # -- alias (produktvalg) ---------------------------------------------
    def _alias_lookup(self, text: str) -> dict | None:
        key = config.normalize_place_text(text)
        return config.ALIASES.get(key)

    # -- oppslag ---------------------------------------------------------
    def resolve(self, text: str, limit: int = 5) -> PlaceResolution:
        """Slå opp stedsnavn. Alias først, deretter Geocoder med ettervalidering."""
        text = (text or "").strip()
        if not text:
            return PlaceResolution(query=text, hit=None)

        alias = self._alias_lookup(text)
        if alias:
            alias_hit = PlaceHit(
                id=alias["stop_place_id"],
                name=alias["name"],
                layer="stopPlace",
                county_id=config.OSTFOLD_COUNTY_ID,
                county=config.OSTFOLD_COUNTY_NAME,
                locality="",
                source=alias["source"],
            )
            # Verifiser at ID-en faktisk finnes og ligger i Østfold (place-oppslag).
            verified = self.verify_ids([alias_hit.id]).get(alias_hit.id)
            if verified is not None:
                verified.source = alias["source"]
                return PlaceResolution(
                    query=text,
                    hit=verified,
                    candidates=[verified],
                    alias_used=True,
                    alias_note=alias.get("note", ""),
                )
            return PlaceResolution(
                query=text,
                hit=alias_hit,
                candidates=[alias_hit],
                alias_used=True,
                alias_note=alias.get("note", "")
                + " (ID kunne ikke verifiseres via geocoder /place)",
            )

        params = {
            "q": text,
            "counties": config.OSTFOLD_COUNTY_ID,
            "layers": config.GEOCODER_LAYERS,
            "limit": str(limit),
        }
        payload = self.client.geocoder_autocomplete(params)
        features = payload.get("features") or []
        candidates: list[PlaceHit] = []
        rejected: list[RejectedFeature] = []
        for rank, feature in enumerate(features):
            hit, rej = validate_feature(feature, rank)
            if hit is not None:
                candidates.append(hit)
            elif rej is not None:
                rejected.append(rej)
        hit = candidates[0] if candidates else None
        ambiguous = False
        if len(candidates) > 1:
            # Tvetydig hvis toppkandidatene har ulike navn og ingen av dem er
            # eksakt lik søketeksten etter normalisering.
            norm = config.normalize_place_text(text)
            ambiguous = config.normalize_place_text(candidates[0].name) != norm
        return PlaceResolution(
            query=text,
            hit=hit,
            candidates=candidates,
            rejected=rejected,
            ambiguous=ambiguous,
        )

    def verify_ids(self, ids: list[str], require_ostfold: bool = True) -> dict[str, PlaceHit]:
        """Batch-oppslag med geocoder /place.

        `require_ostfold=True` (default) brukes ved kilderesolusjon (bare
        Østfold-steder godtas). `False` brukes av scope-vakten, som må se
        fylkestilhørigheten også for steder utenfor Østfold.
        """
        result: dict[str, PlaceHit] = {}
        if not ids:
            return result
        payload = self.client.geocoder_place(list(ids))
        for rank, feature in enumerate(payload.get("features") or []):
            hit, _rej = validate_feature(feature, rank, require_ostfold=require_ostfold)
            if hit is not None:
                result[hit.id] = hit
        return result

    def county_of_stop_place(self, stop_place_id: str) -> str | None:
        """Returner countyId for en StopPlace-ID (cachet). None = ukjent."""
        if not stop_place_id:
            return None
        if stop_place_id in self._county_cache:
            return self._county_cache[stop_place_id]
        hits = self.verify_ids([stop_place_id], require_ostfold=False)
        county = hits[stop_place_id].county_id if stop_place_id in hits else None
        self._county_cache[stop_place_id] = county
        return county

    def counties_of(self, stop_place_ids: list[str]) -> dict[str, str | None]:
        """Batch-oppslag for flere StopPlace-ID-er, med cache."""
        missing = [sid for sid in stop_place_ids if sid and sid not in self._county_cache]
        if missing:
            hits = self.verify_ids(missing, require_ostfold=False)
            for sid in missing:
                self._county_cache[sid] = hits[sid].county_id if sid in hits else None
        return {sid: self._county_cache.get(sid) for sid in stop_place_ids}
