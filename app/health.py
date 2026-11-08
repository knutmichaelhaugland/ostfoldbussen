"""Helsesjekk: ærlige tilstander, ingen falsk HEALTHY.

Komponenter:
- entur: OK / DEGRADED / UNKNOWN (+ last_success). Sjekkes med et lett
  Geocoder-kall (cachet) med mindre HEALTH_ENTUR_CHECK=false.
- db: OK / DEGRADED.
- llm: NOT CONFIGURED (LLM_ENABLED=false) / PENDING (aktivert uten nøkkel) / OK.
- sms: PENDING PROVISIONING (ingen credentials) / DISABLED / OK.

Samlet status er `ok` KUN når entur og db er OK. Ellers `degraded`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from prototype.entur_client import EnturClient, EnturError

from .logging_setup import log


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HealthService:
    def __init__(self, config, db, probe=None, clock=None):
        self.config = config
        self.db = db
        self.started_at = time.monotonic()
        self._probe = probe or self._default_entur_probe
        self._clock = clock or time.monotonic
        self._entur_state = "UNKNOWN"
        self._entur_detail = "ikke sjekket ennå"
        self._entur_last_success: str | None = None
        self._entur_last_check: float | None = None

    # -- entur -----------------------------------------------------------
    def _default_entur_probe(self) -> tuple[bool, str]:
        client = EnturClient(
            client_name=self.config.entur_client_name,
            timeout=self.config.health_entur_timeout_s,
            max_retries=0,
        )
        payload = client.geocoder_autocomplete({"q": "Moss", "limit": "1"})
        if "features" not in payload:
            return False, "geocoder svarte uten features"
        return True, "geocoder svarte"

    def check_entur(self, force: bool = False) -> None:
        if not self.config.health_entur_check:
            self._entur_state = "UNKNOWN"
            self._entur_detail = "HEALTH_ENTUR_CHECK=false"
            return
        now = self._clock()
        if (
            not force
            and self._entur_last_check is not None
            and now - self._entur_last_check < self.config.health_entur_cache_s
        ):
            return
        self._entur_last_check = now
        try:
            ok, detail = self._probe()
        except EnturError as exc:
            self._entur_state = "DEGRADED"
            self._entur_detail = f"EnturError: {exc}"[:200]
            log("entur_health_check", state="DEGRADED")
            return
        except Exception as exc:  # pragma: no cover - ukjent feil skal også rapporteres
            self._entur_state = "DEGRADED"
            self._entur_detail = f"{type(exc).__name__}: {exc}"[:200]
            log("entur_health_check", state="DEGRADED", error=type(exc).__name__)
            return
        if ok:
            self._entur_state = "OK"
            self._entur_detail = detail
            self._entur_last_success = _iso_now()
        else:
            self._entur_state = "DEGRADED"
            self._entur_detail = detail
        log("entur_health_check", state=self._entur_state)

    # -- snapshot --------------------------------------------------------
    def snapshot(self) -> dict:
        self.check_entur()
        db_ok = self.db.healthcheck()
        db_state = "OK" if db_ok else "DEGRADED"

        if self.config.bineric_enabled:
            llm_state = "OK" if self.config.bineric_api_key else "PENDING"
        elif not self.config.llm_enabled:
            llm_state = "NOT CONFIGURED"
        elif not self.config.llm_api_key:
            llm_state = "PENDING"
        else:
            llm_state = "OK"

        inmobile_ready = bool(
            getattr(self.config, "inmobile_outbound_enabled", False)
            and getattr(self.config, "inmobile_api_key", "")
            and getattr(self.config, "inmobile_from", "")
        )
        if inmobile_ready:
            sms_state = "OK"
        elif getattr(self.config, "inmobile_outbound_enabled", False):
            sms_state = "PENDING PROVISIONING"
        else:
            sms_state = "DISABLED"

        overall = "ok" if (db_state == "OK" and self._entur_state == "OK") else "degraded"
        return {
            "status": overall,
            "build_sha": self.config.build_sha,
            "uptime_s": int(self._clock() - self.started_at),
            "checked_at": _iso_now(),
            "components": {
                "entur": {
                    "state": self._entur_state,
                    "last_success": self._entur_last_success,
                    "detail": self._entur_detail,
                },
                "db": {"state": db_state},
                "llm": {"state": llm_state},
                "sms": {"state": sms_state,
                        "outbound_enabled": bool(getattr(self.config, "inmobile_outbound_enabled", False))},
            },
        }
