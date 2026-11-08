"""Observabilitetsmatrise (mandat §9): OBS-01…OBS-14 med ærlige tilstander.

Tilstander: HEALTHY / DEGRADED / UNAVAILABLE / NOT CONFIGURED /
PENDING PROVISIONING / UNKNOWN. En tjeneste er ikke HEALTHY bare fordi en
konfigurasjonsverdi finnes.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"
NOT_CONFIGURED = "NOT CONFIGURED"
PENDING = "PENDING PROVISIONING"
UNKNOWN = "UNKNOWN"


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


class ObservabilityService:
    def __init__(self, config, db, health, started_at: float | None = None):
        self.config = config
        self.db = db
        self.health = health
        self.started_at = started_at or time.monotonic()

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _month_start(self) -> str:
        now = datetime.now(timezone.utc)
        return now.replace(day=1).date().isoformat()

    def _counter(self, today: dict, totals: dict, name: str) -> int:
        return int(today.get(name, 0) or totals.get(name, 0))

    def snapshot(self) -> dict:
        today = self.db.get_counters(self._today())
        totals = self.db.counter_totals()
        month = self.db.counters_since(self._month_start())
        health = self.health.snapshot()
        components = health.get("components", {})
        signals: list[dict] = []

        def add(obs_id: str, name: str, state: str, detail: str) -> None:
            signals.append({"id": obs_id, "name": name, "state": state, "detail": detail})

        uptime = int(time.monotonic() - self.started_at)
        errors_today = int(today.get("errors", 0))
        add("OBS-01", "Applikasjon", HEALTHY if health.get("status") in {"ok", "degraded"} else UNKNOWN,
            f"build {self.config.build_sha}, oppetid {uptime} s, feil i dag {errors_today}")

        entur = components.get("entur", {})
        entur_state = {"OK": HEALTHY, "DEGRADED": DEGRADED}.get(entur.get("state"), UNKNOWN)
        add("OBS-02", "Entur API", entur_state,
            f"siste suksess {entur.get('last_success') or '–'} ({entur.get('detail', '')})")

        geocoder_failures = int(month.get("geocoder_failures", 0))
        add("OBS-03", "Geocoder", HEALTHY if geocoder_failures == 0 else DEGRADED,
            f"mislykkede stedsoppslag denne måneden: {geocoder_failures}")

        routing_failures = int(month.get("routing_failures", 0))
        add("OBS-04", "Journey Planner", HEALTHY if routing_failures == 0 else DEGRADED,
            f"routing-feil denne måneden: {routing_failures}")

        add("OBS-05", "Kjøretøyposisjoner", NOT_CONFIGURED,
            "Sanntidsdiagnostikk brukes ikke av appen")

        llm = components.get("llm", {})
        llm_state = {
            "OK": HEALTHY, "NOT CONFIGURED": NOT_CONFIGURED,
            "PENDING": PENDING, "DEGRADED": DEGRADED,
        }.get(llm.get("state"), UNKNOWN)
        llm_name = "LLM (Bineric)" if self.config.bineric_enabled else "LLM (OpenAI-kompatibel)"
        attempts = int(month.get("llm_attempts", 0))
        successes = int(month.get("llm_success", 0))
        fallbacks = int(month.get("llm_fallbacks", 0))
        add("OBS-06", llm_name, llm_state,
            f"aktivert={str(self.config.llm_enabled or self.config.bineric_enabled).lower()}, "
            f"forsøk={attempts}, vellykket={successes}, fallback={fallbacks}, "
            f"kall={int(month.get('llm_calls', 0))}")

        inmobile_ready = bool(
            getattr(self.config, "inmobile_outbound_enabled", False)
            and getattr(self.config, "inmobile_api_key", "")
            and getattr(self.config, "inmobile_from", "")
        )
        if inmobile_ready:
            sms_state, sms_detail = HEALTHY, "inMobile er konfigurert"
        elif getattr(self.config, "inmobile_outbound_enabled", False):
            sms_state, sms_detail = PENDING, "inMobile aktivert, men nøkkel/avsender mangler"
        else:
            sms_state, sms_detail = NOT_CONFIGURED, "inMobile utsending er ikke aktivert"
        add("OBS-07", "SMS (inMobile)", sms_state, sms_detail)

        requests_today = int(today.get("requests", 0))
        sms_out_today = int(today.get("sms_out", 0))
        add("OBS-08", "Bruk", HEALTHY if components.get("db", {}).get("state") == "OK" else DEGRADED,
            f"{requests_today} forespørsler i dag, {int(month.get('requests', 0))} denne måneden, "
            f"{sms_out_today} SMS ut i dag")

        if not (self.config.sms_unit_cost_nok or self.config.llm_unit_cost_nok):
            cost_state, cost_detail = UNKNOWN, "enhetspriser ikke konfigurert (vises som UKJENT)"
        else:
            cost_state = HEALTHY
            cost_detail = (f"SMS {self.config.sms_unit_cost_nok}/stk, "
                           f"LLM {self.config.llm_unit_cost_nok}/kall")
        add("OBS-09", "Kostnad", cost_state, cost_detail)

        open_reviews = self.db.error_review_counts().get("OPEN", 0)
        add("OBS-10", "Kvalitet", HEALTHY if open_reviews == 0 else DEGRADED,
            f"{open_reviews} åpne poster i feilgjennomgangskøen")

        db_component = components.get("db", {})
        db_state = HEALTHY if db_component.get("state") == "OK" else DEGRADED
        try:
            size_kb = round(os.path.getsize(self.config.database_path) / 1024, 1)
        except OSError:
            size_kb = None
        add("OBS-11", "Database", db_state,
            f"SQLite WAL, størrelse {size_kb} kB" if size_kb is not None else "filsize ukjent")

        mem_state, mem_detail = self._vps_state()
        add("OBS-12", "Miljø", mem_state, mem_detail)

        security_events = (
            int(month.get("security_invalid_signature", 0))
            + int(month.get("security_rate_limited", 0))
            + int(month.get("inbound_rate_limited", 0))
        )
        add("OBS-13", "Sikkerhet", HEALTHY if security_events == 0 else DEGRADED,
            f"{int(month.get('security_invalid_signature', 0))} ugyldige signaturer, "
            f"{int(month.get('security_rate_limited', 0))} rate-limit-hendelser, "
            f"{int(month.get('inbound_rate_limited', 0))} inbound-blokkeringer denne måneden")

        deliveries = self.db.delivery_status_counts()
        failed = (
            deliveries.get("failed", 0)
            + deliveries.get("undelivered", 0)
            + int(month.get("delivery_failures", 0))
        )
        if sms_state in {NOT_CONFIGURED, PENDING}:
            delivery_state = sms_state
            delivery_detail = "ingen ekte levering mulig før inMobile er provisjonert"
        elif failed:
            delivery_state, delivery_detail = DEGRADED, f"{failed} mislykkede leveranser"
        else:
            delivery_state, delivery_detail = HEALTHY, f"{deliveries.get('sent', 0)} sendt"
        add("OBS-14", "Levering", delivery_state, delivery_detail)

        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "build_sha": self.config.build_sha,
            "signals": signals,
        }

    def _vps_state(self) -> tuple[str, str]:
        """Beste forsøk: cgroup-minne og loadavg. Ukjent hvis utilgjengelig."""
        try:
            current = _read("/sys/fs/cgroup/memory.current")
            maximum = _read("/sys/fs/cgroup/memory.max")
            load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
            if current and maximum and maximum.isdigit():
                used_mb = int(current) / (1024 * 1024)
                max_mb = int(maximum) / (1024 * 1024)
                ratio = used_mb / max_mb if max_mb else 0
                state = DEGRADED if ratio > 0.85 else HEALTHY
                return state, (f"minne {used_mb:.0f}/{max_mb:.0f} MiB ({ratio*100:.0f} %), "
                               f"load {load:.2f}" if load is not None else f"minne {used_mb:.0f}/{max_mb:.0f} MiB")
        except OSError:
            pass
        return UNKNOWN, "cgroup/loadavg utilgjengelig i denne konteksten"
