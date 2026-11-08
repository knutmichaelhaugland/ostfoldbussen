"""Terskelmatrise for prototypekjernen (oppgave 4).

Kjører KJERNEN (Entur live) med transferSlack 300/480/600 s og
ganggrenser 250/500 m over 5 reiser x 4 tider. Rapporterer egnet/uegnet/
ingen egnet og tidskonsekvenser (hvor mye senere første egnede avgang er
enn første forslag).

VEDTAR IKKE TERSKEL. Dette er beslutningsgrunnlag, ikke produktvalg.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from . import config, journeys
from .entur_client import EnturClient, EnturError
from .geocoder import PlaceResolver

# Reise-par i Østfold. ID-ene er verifisert i docs/ (GEO-*), men hardkodes
# her bare som TESTUTVALG - de brukes ikke som fasit i tjenestelogikken.
TRIPS = [
    ("Skredderåsen -> Refsnes", "NSR:StopPlace:2636", "NSR:StopPlace:3029"),
    ("Refsnes -> Skredderåsen", "NSR:StopPlace:3029", "NSR:StopPlace:2636"),
    ("Skredderåsen -> Moss bussterminal", "NSR:StopPlace:2636", "NSR:StopPlace:2900"),
    ("Skredderåsen -> Fredrikstad bussterminal", "NSR:StopPlace:2636", "NSR:StopPlace:2306"),
    ("Askim -> Halden bussterminal", "NSR:StopPlace:58793", "NSR:StopPlace:2562"),
]

TIMES = ["08:30", "12:00", "16:30", "20:00"]
SLACKS = [300, 480, 600]
WALK_LIMITS = [250.0, 500.0]
DATE = "2026-11-06"


def build_thresholds(slack: int, walk_limit: float) -> config.Thresholds:
    return config.Thresholds(
        transfer_slack_s=slack,
        minimum_transfer_s=slack,
        warn_transfer_below_s=slack + 120,
        max_walk_m=walk_limit,
        num_trip_patterns=20,
        search_window_minutes=240,
    )


def run_matrix(date: str = DATE, limit: int | None = None) -> dict:
    client = EnturClient()
    resolver = PlaceResolver(client)
    started_at = datetime.now().astimezone()
    started = time.perf_counter()
    cells: list[dict] = []
    calls = 0
    errors: list[dict] = []

    combos = [(trip, time_text) for trip in TRIPS for time_text in TIMES]
    if limit is not None:
        combos = combos[:limit]

    for (trip_name, from_id, to_id), time_text in combos:
        date_time = f"{date}T{time_text}:00+01:00"
        row = {
            "trip": trip_name,
            "time": time_text,
            "date_time": date_time,
            "from": from_id,
            "to": to_id,
            "per_slack": {},
            "meta": {},
        }
        for slack in SLACKS:
            thresholds = build_thresholds(slack, WALK_LIMITS[0])
            call_start = time.perf_counter()
            try:
                result = journeys.search_trips(
                    client, from_id, to_id, date_time,
                    thresholds=thresholds, resolver=resolver,
                )
            except EnturError as exc:
                errors.append(
                    {"trip": trip_name, "time": time_text, "slack": slack, "error": str(exc)}
                )
                row["per_slack"][str(slack)] = {"status": "API_FEIL", "error": str(exc)}
                calls += 1
                continue
            calls += 1
            elapsed_ms = round((time.perf_counter() - call_start) * 1000)
            slack_data = {
                "status": result.status,
                "pattern_count": len(result.itineraries),
                "routing_errors": result.routing_errors,
                "elapsed_ms": elapsed_ms,
                "per_walk_limit": {},
            }
            # Ettervalideringens eget funn: bryter noe forslag minimumsovergangen?
            post_min_slacks = [
                t.slack_s
                for it in result.itineraries
                for t in result.assessments[it.index].transfers
            ]
            short_transfers = [
                s for s in post_min_slacks if s < slack
            ]
            slack_data["postcheck_transfers"] = post_min_slacks
            slack_data["postcheck_short_transfers"] = short_transfers
            for walk_limit in WALK_LIMITS:
                thresholds_walk = build_thresholds(slack, walk_limit)
                assessments = journeys.assess_all(
                    result.itineraries, thresholds_walk, resolver
                )
                suitable_ids = {
                    it.index for it in result.itineraries
                    if assessments[it.index].classification == "EGNET"
                }
                suitable = [it for it in result.itineraries if it.index in suitable_ids]
                unsuitable = [it for it in result.itineraries if it.index not in suitable_ids]
                first_pattern = result.itineraries[0] if result.itineraries else None
                first_suitable = suitable[0] if suitable else None
                extra_wait_min = None
                if (
                    first_suitable is not None
                    and first_pattern is not None
                    and first_suitable.start_dt is not None
                    and first_pattern.start_dt is not None
                ):
                    extra_wait_min = round(
                        (first_suitable.start_dt - first_pattern.start_dt).total_seconds() / 60
                    )
                reasons: dict[str, int] = {}
                for it in unsuitable:
                    for violation in assessments[it.index].violations:
                        key = violation.split(":", 1)[0]
                        reasons[key] = reasons.get(key, 0) + 1
                slack_data["per_walk_limit"][str(int(walk_limit))] = {
                    "patterns": len(result.itineraries),
                    "suitable": len(suitable),
                    "unsuitable": len(unsuitable),
                    "no_suitable": len(suitable) == 0,
                    "first_pattern_start": first_pattern.expected_start if first_pattern else None,
                    "first_suitable_start": first_suitable.expected_start if first_suitable else None,
                    "extra_wait_min": extra_wait_min,
                    "unsuitable_reasons": reasons,
                    "classification": [
                        {
                            "index": it.index,
                            "start": it.expected_start,
                            "end": it.expected_end,
                            "classification": assessments[it.index].classification,
                            "violations": assessments[it.index].violations,
                            "walk_m": assessments[it.index].walk_total_m,
                            "transfers": [t.slack_s for t in assessments[it.index].transfers],
                            "scope": assessments[it.index].scope.status
                            if assessments[it.index].scope
                            else None,
                        }
                        for it in result.itineraries
                    ],
                }
            row["per_slack"][str(slack)] = slack_data
        cells.append(row)
        print(
            f"[matrix] {trip_name} {time_text} ferdig",
            file=sys.stderr,
            flush=True,
        )

    elapsed_s = round(time.perf_counter() - started, 1)
    aggregate = _aggregate(cells)
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "started_at": started_at.isoformat(),
        "duration_s": elapsed_s,
        "api_calls": calls,
        "errors": errors,
        "config": {
            "date": date,
            "slacks_s": SLACKS,
            "walk_limits_m": [int(w) for w in WALK_LIMITS],
            "trips": [{"name": name, "from": f, "to": t} for name, f, t in TRIPS],
            "times": TIMES,
            "num_trip_patterns": 20,
            "search_window_minutes": 240,
            "minimum_transfer_s": "= transferSlack (ettervalidering)",
            "note": "Ingen terskel er vedtatt. Dette er beslutningsgrunnlag.",
        },
        "aggregate": aggregate,
        "cells": cells,
    }


def _aggregate(cells: list[dict]) -> dict:
    agg: dict = {}
    for slack in SLACKS:
        for walk_limit in WALK_LIMITS:
            key = f"slack{slack}_walk{int(walk_limit)}"
            suitable = 0
            unsuitable = 0
            none = 0
            total_patterns = 0
            extra_waits: list[int] = []
            short_transfer_cells = 0
            for cell in cells:
                slack_data = cell["per_slack"].get(str(slack), {})
                walk_data = (slack_data.get("per_walk_limit") or {}).get(str(int(walk_limit)), {})
                total_patterns += walk_data.get("patterns", 0)
                if walk_data.get("no_suitable"):
                    none += 1
                else:
                    suitable += 1
                if walk_data.get("extra_wait_min") is not None:
                    extra_waits.append(walk_data["extra_wait_min"])
                if slack_data.get("postcheck_short_transfers"):
                    short_transfer_cells += 1
            agg[key] = {
                "cells": len(cells),
                "cells_with_suitable": suitable,
                "cells_without_suitable": none,
                "total_patterns": total_patterns,
                "extra_wait_min_min": min(extra_waits) if extra_waits else None,
                "extra_wait_min_max": max(extra_waits) if extra_waits else None,
                "extra_wait_min_avg": round(sum(extra_waits) / len(extra_waits), 1) if extra_waits else None,
                "cells_with_postcheck_short_transfer": short_transfer_cells,
            }
    return agg


def to_markdown(matrix: dict) -> str:
    lines: list[str] = []
    lines.append("# Terskelmatrise (prototypekjerne, live Entur)")
    lines.append("")
    lines.append(f"Generert: {matrix['generated_at']} · varighet {matrix['duration_s']} s · "
                 f"{matrix['api_calls']} trip-kall · status: kun beslutningsgrunnlag, INGEN terskel vedtatt.")
    lines.append("")
    lines.append("## Oppsett")
    lines.append("")
    lines.append(f"- Dato: {matrix['config']['date']}, tider: {', '.join(matrix['config']['times'])}")
    lines.append(f"- transferSlack: {matrix['config']['slacks_s']} s")
    lines.append(f"- ganggrense (sum, hard): {matrix['config']['walk_limits_m']} m")
    lines.append("- Ettervalidering: overgang = nesteTransitStart - forrigeTransitSlutt, "
                 "sjekkes mot samme verdi som transferSlack (API-default ellers).")
    lines.append("")
    lines.append("## Aggregat")
    lines.append("")
    lines.append("| transferSlack | ganggrense | celler med egnet | celler uten egnet | forslag totalt | "
                 "ekstra ventetid min/snitt/maks (min) | celler der ettervalidering fant kort bytte |")
    lines.append("|---:|---:|---:|---:|---:|---|---:|")
    for slack in matrix["config"]["slacks_s"]:
        for walk_limit in matrix["config"]["walk_limits_m"]:
            key = f"slack{slack}_walk{int(walk_limit)}"
            data = matrix["aggregate"][key]
            extra = (
                f"{data['extra_wait_min_min']}/{data['extra_wait_min_avg']}/{data['extra_wait_min_max']}"
                if data["extra_wait_min_avg"] is not None else "-"
            )
            lines.append(
                f"| {slack} | {walk_limit} | {data['cells_with_suitable']}/{data['cells']} | "
                f"{data['cells_without_suitable']} | {data['total_patterns']} | {extra} | "
                f"{data['cells_with_postcheck_short_transfer']} |"
            )
    lines.append("")
    lines.append("## Per reise x tid (walk=500 m)")
    lines.append("")
    header = "| Reise | Tid |"
    sep = "|---|---|"
    for slack in matrix["config"]["slacks_s"]:
        header += f" slack {slack} (egnet/antall, første egnet) |"
        sep += "---|"
    lines.append(header)
    lines.append(sep)
    for cell in matrix["cells"]:
        row = f"| {cell['trip']} | {cell['time']} |"
        for slack in matrix["config"]["slacks_s"]:
            data = cell["per_slack"].get(str(slack), {})
            walk = (data.get("per_walk_limit") or {}).get("500", {})
            if walk.get("no_suitable"):
                value = "INGEN EGNET"
            elif walk:
                early = (walk.get("first_suitable_start") or "")[11:16]
                extra = walk.get("extra_wait_min")
                value = f"{walk.get('suitable')}/{walk.get('patterns')} {early}"
                if extra:
                    value += f" (+{extra} min)"
            else:
                value = "API-feil"
            row += f" {value} |"
        lines.append(row)
    lines.append("")
    lines.append("## Per reise x tid (walk=250 m)")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for cell in matrix["cells"]:
        row = f"| {cell['trip']} | {cell['time']} |"
        for slack in matrix["config"]["slacks_s"]:
            data = cell["per_slack"].get(str(slack), {})
            walk = (data.get("per_walk_limit") or {}).get("250", {})
            if walk.get("no_suitable"):
                value = "INGEN EGNET"
            elif walk:
                early = (walk.get("first_suitable_start") or "")[11:16]
                extra = walk.get("extra_wait_min")
                value = f"{walk.get('suitable')}/{walk.get('patterns')} {early}"
                if extra:
                    value += f" (+{extra} min)"
            else:
                value = "API-feil"
            row += f" {value} |"
        lines.append(row)
    lines.append("")
    lines.append("## API-håndhevelse av transferSlack (ettervalidering)")
    lines.append("")
    lines.append("Kolonne: antall forslag der ettervalideringen fant overgang < valgt transferSlack. "
                 "Skal være 0 hvis API-et håndhever grensen hardt.")
    lines.append("")
    lines.append("| transferSlack | celler der ettervalidering fant kort bytte |")
    lines.append("|---:|---:|")
    for slack in matrix["config"]["slacks_s"]:
        for walk_limit in matrix["config"]["walk_limits_m"]:
            key = f"slack{slack}_walk{int(walk_limit)}"
            lines.append(
                f"| {slack} | {matrix['aggregate'][key]['cells_with_postcheck_short_transfer']} |"
            )
    if matrix["errors"]:
        lines.append("")
        lines.append("## API-feil")
        lines.append("")
        for err in matrix["errors"]:
            lines.append(f"- {err['trip']} {err['time']} slack={err['slack']}: {err['error']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Terskelmatrise for prototypekjernen")
    parser.add_argument("--date", default=DATE)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--limit", type=int, default=None,
                        help="begrens antall reise x tid-celler (for royktest)")
    args = parser.parse_args(argv)
    matrix = run_matrix(date=args.date, limit=args.limit)
    with open(args.out_json, "w", encoding="utf-8") as handle:
        json.dump(matrix, handle, ensure_ascii=False, indent=2)
    with open(args.out_md, "w", encoding="utf-8") as handle:
        handle.write(to_markdown(matrix))
    print(
        f"[matrix] skrev {args.out_json} og {args.out_md} "
        f"({matrix['api_calls']} kall, {matrix['duration_s']} s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
