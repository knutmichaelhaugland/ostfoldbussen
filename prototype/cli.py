"""Prototype-CLI for den isolerte Entur-kjernen.

Kjor:
  python3 -m prototype.cli "Når går buss 22 fra Skredderåsen?"
  python3 -m prototype.cli "Hvordan kommer jeg fra Skredderåsen til Refsnes?"

Viser tolket intensjon, Entur-ID-er, API-resultat, valgt reise/avganger,
advarsler, SMS-utkast, SMS-segmenter og responstid.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from . import config, formatting, geocoder, intent as intent_module, journeys, sms
from .departures import get_departures
from .entur_client import EnturClient, EnturError

EXIT_OK = 0
EXIT_UNRESOLVED = 1
EXIT_API_ERROR = 2


def _resolution_dict(res: geocoder.PlaceResolution | None) -> dict | None:
    if res is None:
        return None
    hit = res.hit
    return {
        "query": res.query,
        "found": res.found,
        "id": hit.id if hit else None,
        "name": hit.name if hit else None,
        "layer": hit.layer if hit else None,
        "county_id": hit.county_id if hit else None,
        "county": hit.county if hit else None,
        "source": hit.source if hit else None,
        "alias_used": res.alias_used,
        "alias_note": res.alias_note,
        "ambiguous": res.ambiguous,
        "candidates": [
            {"id": c.id, "name": c.name, "county_id": c.county_id, "layer": c.layer}
            for c in res.candidates
        ],
        "rejected": [
            {"id": r.id, "name": r.name, "layer": r.layer, "county_id": r.county_id, "reason": r.reason}
            for r in res.rejected
        ],
    }


def _departure_dict(dep) -> dict:
    return {
        "line": dep.line_public_code,
        "line_id": dep.line_id,
        "mode": dep.transport_mode,
        "direction": dep.direction,
        "aimed": dep.aimed,
        "expected": dep.expected,
        "display_time": dep.departure_time,
        "realtime": dep.realtime,
        "timetable_only": dep.is_timetable_only,
        "delay_s": dep.delay_seconds,
        "cancellation": dep.cancellation,
        "prediction_inaccurate": dep.prediction_inaccurate,
        "quay_public_code": dep.quay_public_code,
        "situations": dep.situations,
    }


def _assessment_dict(assessment) -> dict:
    scope = assessment.scope
    return {
        "classification": assessment.classification,
        "violations": assessment.violations,
        "walk_total_m": assessment.walk_total_m,
        "walk_legs_m": assessment.walk_legs_m,
        "walk_total_s": assessment.walk_total_s,
        "transfers": [
            {
                "at": t.at_stop_name,
                "from_line": t.from_line,
                "to_line": t.to_line,
                "arrival_time": t.arrival_time,
                "departure_time": t.departure_time,
                "slack_s": t.slack_s,
                "minimum_s": t.minimum_s,
                "is_short": t.is_short,
                "is_warn_only": t.is_warn_only,
            }
            for t in assessment.transfers
        ],
        "scope": {
            "status": scope.status,
            "outside": scope.outside,
            "intermediate_stop_ids": scope.intermediate_stop_ids,
            "counties": scope.counties,
            "error": scope.error,
        }
        if scope is not None
        else None,
    }


def _itinerary_dict(it, assessment) -> dict:
    data = {
        "index": it.index,
        "start": it.expected_start,
        "end": it.expected_end,
        "duration_s": it.duration_s,
        "walk_time_s": it.walk_time_s,
        "waiting_time_s": it.waiting_time_s,
        "distance_m": it.distance_m,
        "realtime": it.has_realtime,
        "legs": [
            {
                "mode": leg.mode,
                "line": leg.line_public_code,
                "from": leg.from_ref.name,
                "to": leg.to_ref.name,
                "start": leg.expected_start,
                "end": leg.expected_end,
                "distance_m": leg.distance_m,
                "realtime": leg.realtime,
            }
            for leg in it.legs
        ],
    }
    if assessment is not None:
        data["assessment"] = _assessment_dict(assessment)
    return data


def _print_header(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _render_departures(report: dict) -> None:
    _print_header("TOLKET INTENSJON")
    for line in formatting.intent_block(report["intent"]):
        print(line)
    _print_header("ENTUR-ID-ER")
    for key, res in report["places"].items():
        if res is None:
            continue
        status = "funnet" if res["found"] else "IKKE FUNNET"
        print(f"  {key}: {res['query']!r} -> {res['id']} ({res['name']}) [{status}]")
        print(
            f"    layer={res['layer']} county={res['county']} ({res['county_id']}) "
            f"kilde={res['source']}"
        )
        if res["alias_used"]:
            print(f"    ALIAS (produktvalg): {res['alias_note']}")
        if res["ambiguous"]:
            print(f"    TVETYDIG: {len(res['candidates'])} kandidater - valgte forste")
        for rejected in res["rejected"][:3]:
            print(
                f"    forkastet: {rejected['id']} {rejected['name']} "
                f"({rejected['reason']}, county={rejected['county_id']})"
            )
    api = report["api"]
    _print_header("API-RESULTAT")
    print(f"  operasjon: {api['operation']}")
    print(f"  kall: {api['call_count']} stk, HTTP-status: {api['statuses']}")
    print(f"  holdeplass: {api['stop_name']} ({api['stop_place_id']})")
    print(
        f"  avganger i vinduet: {api['all_departures_count']}, "
        f"etter linjefilter {api['line_filter']!r}: {api['matched']}"
    )
    print(f"  realtime: {api['realtime_count']}/{api['matched']} har sanntid")
    if api.get("partial_errors"):
        print(f"  PARTIAL ERRORS: {api['partial_errors']}")

    _print_header("AVGANGER (API-resultat, forste 10)")
    if not report["departures"]:
        print("  (ingen)")
    for dep in report["departures"][:10]:
        marker = "sanntid" if dep["realtime"] else "rutetider"
        print(
            f"  {formatting.format_clock(dep['display_time']):>5} linje {dep['line']:>3} "
            f"mot {dep['direction']:<22} [{marker}]"
        )
    _print_header("ADVARSLER")
    if not report["warnings"]:
        print("  (ingen)")
    for warning in report["warnings"]:
        print(f"  - {warning}")


def _render_trip(report: dict) -> None:
    _render_common_intent(report)
    api = report["api"]
    _print_header("API-RESULTAT")
    print(f"  operasjon: trip, transferSlack={api['transfer_slack_s']}s, "
          f"numTripPatterns={api['num_trip_patterns']}, dateTime={api['date_time']}")
    print(f"  HTTP-statuser: {api['statuses']}, status: {api['status']}")
    print(f"  forslag: {api['pattern_count']}")
    if api.get("routing_errors"):
        print(f"  ROUTING ERRORS: {api['routing_errors']}")
    if api.get("partial_errors"):
        print(f"  PARTIAL ERRORS: {api['partial_errors']}")

    _print_header("REISEFORSLAG (API-resultat)")
    for it, assessment in report["itineraries"]:
        scope = assessment["scope"]
        scope_text = "scope=OK" if scope and scope["status"] == "OK" else f"scope={scope['status'] if scope else '?'}"
        print(
            f"  #{it['index']} {formatting.format_clock(it['start'])}-"
            f"{formatting.format_clock(it['end'])} "
            f"{formatting.format_minutes(it['duration_s'])} "
            f"bytter={len(assessment['transfers'])} "
            f"gange={assessment['walk_total_m']:.0f}m "
            f"{assessment['classification']} {scope_text}"
        )
    selected = report["selected"]
    _print_header("VALGT REISE + BYTTER")
    if selected["index"] is None:
        print("  (ingen reise valgt)")
    else:
        it, assessment = report["itineraries"][selected["index"]]
        print(f"  valg: forslag #{it['index']} - {selected['reason']}")
        print(
            f"  {formatting.format_clock(it['start'])} -> {formatting.format_clock(it['end'])} "
            f"({formatting.format_minutes(it['duration_s'])})"
        )
        for step in formatting.itinerary_steps(
            report["_selected_itinerary"]
        ):
            print(f"    {step}")
        print(f"  bytter: {len(assessment['transfers'])}")
        for transfer in assessment["transfers"]:
            flag = (
                "KORT"
                if transfer["is_short"]
                else ("stramt" if transfer["is_warn_only"] else "ok")
            )
            print(
                f"    {formatting.format_clock(transfer['arrival_time'])} -> "
                f"{formatting.format_clock(transfer['departure_time'])} "
                f"{transfer['at']}: {transfer['slack_s']}s "
                f"(minimum {transfer['minimum_s']}s) [{flag}]"
            )
        print(f"  gange totalt: {assessment['walk_total_m']:.0f} m "
              f"({formatting.format_minutes(assessment['walk_total_s'])})")
        scope = assessment["scope"]
        print(f"  scope-vakt: {scope['status']}")
        for item in scope["outside"]:
            print(
                f"    UTENFOR ØSTFOLD: {item['name']} ({item['stop_place_id']}) "
                f"countyId={item['county_id']} - FLAGGET, ikke skjult"
            )
        if scope.get("error"):
            print(f"    scope-feil: {scope['error']}")

    _print_header("ADVARSLER")
    if not report["warnings"]:
        print("  (ingen)")
    for warning in report["warnings"]:
        print(f"  - {warning}")


def _render_common_intent(report: dict) -> None:
    _print_header("TOLKET INTENSJON")
    for line in formatting.intent_block(report["intent"]):
        print(line)
    _print_header("ENTUR-ID-ER")
    for key, res in report["places"].items():
        if res is None:
            continue
        status = "funnet" if res["found"] else "IKKE FUNNET"
        print(f"  {key}: {res['query']!r} -> {res['id']} ({res['name']}) [{status}]")
        print(
            f"    layer={res['layer']} county={res['county']} ({res['county_id']}) "
            f"kilde={res['source']}"
        )
        if res["alias_used"]:
            print(f"    ALIAS (produktvalg): {res['alias_note']}")
        if res["ambiguous"]:
            print(f"    TVETYDIG: {len(res['candidates'])} kandidater - valgte forste")
        for rejected in res["rejected"][:3]:
            print(
                f"    forkastet: {rejected['id']} {rejected['name']} "
                f"({rejected['reason']}, county={rejected['county_id']})"
            )


def _render_sms(report: dict) -> None:
    _print_header("SMS-UTKAST")
    print(f"  {report['sms']['text']}")
    _print_header("SMS-SEGMENTER")
    seg = report["sms"]["segments"]
    print(
        f"  {seg['encoding']}: {seg['segments']} segment(er), "
        f"{seg['units']}/{seg['per_segment']} per segment, {seg['chars']} tegn, "
        f"gsm7_safe={seg['gsm7_safe']}"
    )
    _print_header("RESPONSTID")
    print(f"  {report['response_time_ms']} ms (inkl. {report['api']['call_count']} Entur-kall)")
    print()


def _build_thresholds(args) -> config.Thresholds:
    return config.Thresholds(
        transfer_slack_s=args.transfer_slack,
        minimum_transfer_s=args.min_transfer,
        warn_transfer_below_s=args.warn_transfer,
        max_walk_m=args.max_walk,
        max_walk_leg_m=args.max_walk_leg,
        max_walk_time_s=args.max_walk_time,
        num_trip_patterns=args.num_patterns,
        search_window_minutes=args.search_window,
    )


def run(question: str, args, client: EnturClient, now: datetime | None = None) -> tuple[dict, int]:
    started = time.perf_counter()
    now = now or datetime.now().astimezone()
    intent = intent_module.interpret(question, now=now)
    resolver = geocoder.PlaceResolver(client)
    thresholds = _build_thresholds(args)

    report: dict = {
        "question": question,
        "intent": {
            "kind": intent.kind,
            "from_text": intent.from_text,
            "to_text": intent.to_text,
            "line_code": intent.line_code,
            "time_text": intent.time_text,
            "target_datetime": intent.target_datetime,
            "notes": intent.notes,
        },
        "places": {},
        "api": {"call_count": 0, "statuses": []},
        "warnings": [],
        "thresholds": {
            "transfer_slack_s": thresholds.transfer_slack_s,
            "minimum_transfer_s": thresholds.minimum_transfer_s,
            "warn_transfer_below_s": thresholds.warn_transfer_below_s,
            "max_walk_m": thresholds.max_walk_m,
            "num_trip_patterns": thresholds.num_trip_patterns,
        },
        "response_time_ms": 0,
    }

    if intent.kind == "UNKNOWN":
        report["warnings"] = ["intensjonen ble ikke gjenkjent - prov et klarere sporsmal"]
        report["response_time_ms"] = round((time.perf_counter() - started) * 1000)
        return report, EXIT_UNRESOLVED

    # --- stedsoppslag ---
    from_res = resolver.resolve(intent.from_text) if intent.from_text else None
    report["places"]["fra"] = _resolution_dict(from_res)
    to_res = None
    if intent.is_trip:
        to_res = resolver.resolve(intent.to_text) if intent.to_text else None
        report["places"]["til"] = _resolution_dict(to_res)

    if from_res is None or not from_res.found or (intent.is_trip and (to_res is None or not to_res.found)):
        report["warnings"].append("fant ikke stedet i Østfold - ingen API-kall for reise/avganger")
        if from_res is not None and not from_res.found:
            report["warnings"].append(f"fra: {intent.from_text!r} ga ingen godkjent stopPlace i Østfold")
        if intent.is_trip and to_res is not None and not to_res.found:
            report["warnings"].append(f"til: {intent.to_text!r} ga ingen godkjent stopPlace i Østfold")
        report["response_time_ms"] = round((time.perf_counter() - started) * 1000)
        return report, EXIT_UNRESOLVED

    try:
        if intent.is_departures:
            wanted = max(thresholds.departures_window, 100 if intent.line_code else 40)
            stop_dep = get_departures(
                client,
                from_res.hit.id,
                number_of_departures=wanted,
                line_public_code=intent.line_code or None,
                start_time=intent.target_datetime or None,
            )
            report["api"].update(
                {
                    "operation": "stopPlace.estimatedCalls",
                    "stop_place_id": from_res.hit.id,
                    "stop_name": stop_dep.stop_name if stop_dep else None,
                    "all_departures_count": stop_dep.all_departures_count if stop_dep else 0,
                    "line_filter": intent.line_code or None,
                    "matched": len(stop_dep.departures) if stop_dep else 0,
                    "realtime_count": stop_dep.realtime_count if stop_dep else 0,
                    "partial_errors": stop_dep.partial_errors if stop_dep else [],
                }
            )
            if stop_dep is None:
                report["warnings"].append("ukjent StopPlace-ID: data.stopPlace=null (API-feil, ikke tomt svar)")
            else:
                report["departures"] = [_departure_dict(d) for d in stop_dep.departures]
                report["warnings"] = formatting.departure_warnings(stop_dep)
                sms_text = formatting.format_departures_sms(stop_dep)
                seg = sms.count_segments(sms_text)
                report["sms"] = {
                    "text": sms_text,
                    "segments": {
                        "encoding": seg.encoding,
                        "segments": seg.segments,
                        "units": seg.units,
                        "per_segment": seg.per_segment,
                        "chars": seg.chars,
                        "gsm7_safe": seg.gsm7_safe,
                    },
                }
        else:
            result = journeys.search_trips(
                client,
                from_res.hit.id,
                to_res.hit.id,
                intent.target_datetime,
                thresholds=thresholds,
                resolver=resolver,
            )
            selection = journeys.select_itinerary(result.itineraries, result.assessments)
            report["api"].update(
                {
                    "operation": "trip",
                    "transfer_slack_s": result.transfer_slack_s,
                    "num_trip_patterns": thresholds.num_trip_patterns,
                    "date_time": intent.target_datetime,
                    "status": result.status,
                    "pattern_count": len(result.itineraries),
                    "routing_errors": result.routing_errors,
                    "partial_errors": result.partial_errors,
                }
            )
            report["itineraries"] = [
                (_itinerary_dict(it, result.assessments[it.index]),
                 _assessment_dict(result.assessments[it.index]))
                for it in result.itineraries
            ]
            report["selected"] = {
                "index": selection.itinerary.index if selection.itinerary else None,
                "reason": selection.reason,
            }
            report["_selected_itinerary"] = selection.itinerary
            report["warnings"] = []
            if result.status == "RUTING_FEIL":
                report["warnings"].append(
                    "rutingfeil fra Entur: "
                    + "; ".join(
                        f"{e.get('code')}: {e.get('description')}" for e in result.routing_errors
                    )
                )
            if result.status == "INGEN_FORSLAG":
                report["warnings"].append("ingen reiseforslag i vinduet")
            if selection.itinerary is not None:
                report["warnings"].extend(
                    formatting.itinerary_warnings(
                        selection.itinerary, selection.assessment, thresholds
                    )
                )
                if selection.reason == "egnet, men scope-vakt flagget":
                    report["warnings"].insert(0, "valgt reise er FLAGGET av scope-vakten")
            sms_text = formatting.format_trip_sms(selection.itinerary, selection.assessment)
            seg = sms.count_segments(sms_text)
            report["sms"] = {
                "text": sms_text,
                "segments": {
                    "encoding": seg.encoding,
                    "segments": seg.segments,
                    "units": seg.units,
                    "per_segment": seg.per_segment,
                    "chars": seg.chars,
                    "gsm7_safe": seg.gsm7_safe,
                },
            }
    except EnturError as exc:
        report["warnings"].append(f"Entur-feil: {exc}")
        report["response_time_ms"] = round((time.perf_counter() - started) * 1000)
        return report, EXIT_API_ERROR

    report["api"]["call_count"] = len(client.calls)
    report["api"]["statuses"] = [c.status for c in client.calls]
    report["response_time_ms"] = round((time.perf_counter() - started) * 1000)
    return report, EXIT_OK


def _render(report: dict) -> None:
    print(f"SPORSMAAL: {report['question']}")
    if report["intent"]["kind"] == "UNKNOWN":
        _print_header("TOLKET INTENSJON")
        for line in formatting.intent_block(report["intent"]):
            print(line)
        _print_header("ADVARSLER")
        for warning in report["warnings"]:
            print(f"  - {warning}")
        return
    if "departures" in report:
        _render_departures(report)
    else:
        _render_trip(report)
    if "sms" in report:
        _render_sms(report)


def _jsonable(value):
    """Fjern interne nøkler og dataclass-objekter for JSON-utskrift."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prototype.cli",
        description="Isolert, lokal Entur-kjerne for Østfoldbussen (prototype).",
    )
    parser.add_argument("question", help="norsk spørsmål, f.eks. 'Når går buss 22 fra Skredderåsen?'")
    parser.add_argument("--transfer-slack", type=int, default=120,
                        help="transferSlack sendt til API (sekunder; API-default 120)")
    parser.add_argument("--min-transfer", type=int, default=None,
                        help="ettervalideringsminimum for overgang (sekunder; default = transfer-slack)")
    parser.add_argument("--warn-transfer", type=int, default=300,
                        help="advarselsgrense for stramt bytte (sekunder; ikke filter)")
    parser.add_argument("--max-walk", type=float, default=None,
                        help="maks sum gangavstand i meter (hard grense; default ingen)")
    parser.add_argument("--max-walk-leg", type=float, default=None,
                        help="maks gangavstand per bein i meter (hard grense)")
    parser.add_argument("--max-walk-time", type=int, default=None,
                        help="maks sum gangtid i sekunder (hard grense)")
    parser.add_argument("--num-patterns", type=int, default=10, help="numTripPatterns")
    parser.add_argument("--search-window", type=int, default=None, help="searchWindow (minutter)")
    parser.add_argument("--now", default=None,
                        help="fast referansetid (ISO 8601) for reproduserbare kjøringer")
    parser.add_argument("--json", action="store_true", help="skriv maskinlesbar JSON i stedet")
    parser.add_argument("--save-raw", default=None,
                        help="lagre rå Entur-svar (JSON) til denne filen")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else None
    client = EnturClient(capture_raw=bool(args.save_raw))
    try:
        report, exit_code = run(args.question, args, client, now=now)
    except EnturError as exc:
        print(f"FATAL Entur-feil: {exc}", file=sys.stderr)
        return EXIT_API_ERROR

    if args.json:
        print(json.dumps(_jsonable(report), ensure_ascii=False, indent=2, default=str))
    else:
        _render(report)

    if args.save_raw:
        with open(args.save_raw, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "question": args.question,
                    "intent": report["intent"],
                    "captured_at": datetime.now().astimezone().isoformat(),
                    "api_calls": _jsonable(report["api"]),
                    "raw_captures": client.raw_captures,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Rå Entur-svar lagret: {args.save_raw}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
