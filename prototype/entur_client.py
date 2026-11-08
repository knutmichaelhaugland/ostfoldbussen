"""Entur-klient (stdlib urllib/json) med timeout, 429-backoff og validering.

Verifiserte fakta denne modulen bygger på (se docs/):
- GraphQL: HTTP 200 selv ved feil; `data` kan vaere null, `errors` kan finnes
  alene eller sammen med data (partial errors). Klienten MAA validere begge.
- 429 har INGEN `Retry-After`; kvote-429 har `rate-limit-expiry-time`
  (format: `Thu Nov 05 2026 18:34:47 GMT-0000 (GMT)`). Spike-429 har
  `spike-allowed`/`spike-range` og ingen `rate-limit-*`.
- Geocoder v3 bruker `q` (ikke `text`) og `place?ids=` for batch-oppslag.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config


class EnturError(Exception):
    """Basisklasse for alle Entur-feil i prototypen."""


class EnturTransportError(EnturError):
    """Nettverk/timeout - forespørselen kom aldri fram."""


class EnturHTTPError(EnturError):
    def __init__(self, status: int, body: str, url: str = ""):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} fra {url}: {body[:200]}")


class EnturRateLimited(EnturError):
    """429 etter at retry-budsjettet er brukt opp."""

    def __init__(self, status: int, body: str, retries: int, waited_s: float):
        self.status = status
        self.body = body
        self.retries = retries
        self.waited_s = waited_s
        super().__init__(f"429 etter {retries} retry (ventet {waited_s:.2f}s): {body[:160]}")


class EnturProtocolError(EnturError):
    """Svar som ikke er gyldig JSON / mangler forventet struktur."""


class EnturGraphQLError(EnturError):
    """GraphQL-errors der det ikke finnes brukbare data."""

    def __init__(self, errors: list, partial: bool = False):
        self.errors = errors or []
        self.partial = partial
        msg = "; ".join(_error_message(e) for e in self.errors[:3]) or "ukjent GraphQL-feil"
        super().__init__(msg)


def _error_message(err) -> str:
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)


@dataclass
class HttpResponse:
    status: int
    headers: dict  # lower-case nøkler
    body: bytes
    url: str = ""
    elapsed_s: float = 0.0

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def json(self):
        return json.loads(self.text)


@dataclass
class CallRecord:
    method: str
    url: str
    status: int = 0
    elapsed_s: float = 0.0
    attempt: int = 1
    rate_limited: bool = False
    partial_errors: list = field(default_factory=list)


class UrllibTransport:
    """Tynn wrapper rundt urllib.request. Kan byttes ut i tester."""

    def __init__(self, timeout: float = config.DEFAULT_TIMEOUT_S):
        self.timeout = timeout

    def request(self, method: str, url: str, headers: dict, body: bytes | None = None) -> HttpResponse:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
                return HttpResponse(
                    status=int(getattr(resp, "status", 200)),
                    headers={str(k).lower(): v for k, v in resp.headers.items()},
                    body=data,
                    url=url,
                    elapsed_s=time.monotonic() - start,
                )
        except urllib.error.HTTPError as exc:  # 4xx/5xx
            data = exc.read() if hasattr(exc, "read") else b""
            return HttpResponse(
                status=int(exc.code),
                headers={str(k).lower(): v for k, v in (exc.headers or {}).items()},
                body=data,
                url=url,
                elapsed_s=time.monotonic() - start,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EnturTransportError(f"nettverksfeil mot {url}: {exc}") from exc


_EXPIRY_RE = re.compile(
    r"(\w{3}) (\w{3}) (\d{1,2}) (\d{4}) (\d{2}):(\d{2}):(\d{2})"
)


def parse_rate_limit_expiry(value: str | None, now: float | None = None) -> float | None:
    """Tolk `rate-limit-expiry-time` -> sekunder aa vente (>=0), ellers None.

    Format observert: `Thu Nov 05 2026 18:34:47 GMT-0000 (GMT)`.
    Vi parser feltene eksplisitt og behandler tidssonen som UTC (GMT-0000).
    Returnerer antall sekunder fra `now` (default time.time()) til utløp.
    """
    if not value:
        return None
    m = _EXPIRY_RE.search(str(value))
    if not m:
        return None
    _, mon, day, year, hh, mm, ss = m.groups()
    try:
        dt = datetime.strptime(
            f"{day} {mon} {year} {hh}:{mm}:{ss}", "%d %b %Y %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    ref = time.time() if now is None else now
    return max(0.0, dt.timestamp() - ref)


class EnturClient:
    """Entur-klient for Journey Planner v3 (GraphQL) og Geocoder v3 (GET)."""

    def __init__(
        self,
        transport=None,
        client_name: str = config.ET_CLIENT_NAME,
        timeout: float = config.DEFAULT_TIMEOUT_S,
        max_retries: int = config.DEFAULT_MAX_RETRIES,
        sleep=time.sleep,
        clock=time.time,
        capture_raw: bool = False,
    ):
        self.transport = transport or UrllibTransport(timeout=timeout)
        self.client_name = client_name
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self.capture_raw = capture_raw
        self.raw_captures: list[dict] = []
        self.calls: list[CallRecord] = []
        self.last_errors: list = []
        self.partial_errors: list = []
        self.last_response: HttpResponse | None = None
        self.rate_limit_wait_s = 0.0

    # -- offentlig API ---------------------------------------------------
    @property
    def base_headers(self) -> dict:
        return {
            "ET-Client-Name": self.client_name,
            "Accept": "application/json",
            "User-Agent": "ostfoldbussen-prototype/0.1 (stdlib)",
        }

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        payload: dict = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        body = json.dumps(payload).encode("utf-8")
        headers = dict(self.base_headers)
        headers["Content-Type"] = "application/json"
        return self._request_with_backoff(
            "POST", config.JOURNEY_PLANNER_URL, headers, body, operation="graphql"
        )

    def geocoder_autocomplete(self, params: dict) -> dict:
        url = config.GEOCODER_AUTOCOMPLETE_URL + "?" + urllib.parse.urlencode(params)
        return self._request_with_backoff(
            "GET", url, dict(self.base_headers), None, operation="geocoder-autocomplete"
        )

    def geocoder_place(self, ids: list[str], lang: str = "no") -> dict:
        params = {"ids": ",".join(ids), "lang": lang}
        url = config.GEOCODER_PLACE_URL + "?" + urllib.parse.urlencode(params)
        return self._request_with_backoff(
            "GET", url, dict(self.base_headers), None, operation="geocoder-place"
        )

    # -- intern maskin ---------------------------------------------------
    def _request_with_backoff(
        self, method: str, url: str, headers: dict, body: bytes | None, operation: str
    ) -> dict:
        attempt = 0
        waited = 0.0
        while True:
            attempt += 1
            record = CallRecord(method=method, url=url, attempt=attempt)
            self.calls.append(record)
            resp = self.transport.request(method, url, headers, body)
            self.last_response = resp
            record.status = resp.status
            record.elapsed_s = resp.elapsed_s
            if self.capture_raw:
                self.raw_captures.append(
                    {
                        "operation": operation,
                        "method": method,
                        "url": url,
                        "status": resp.status,
                        "attempt": attempt,
                        "headers": {
                            k: v
                            for k, v in resp.headers.items()
                            if k.startswith("rate-limit-") or k in ("content-type", "date")
                        },
                        "body": resp.text[:200_000],
                    }
                )

            if resp.status == 429:
                record.rate_limited = True
                if attempt > self.max_retries:
                    raise EnturRateLimited(resp.status, resp.text, attempt - 1, waited)
                delay = self._retry_delay(resp, attempt)
                waited += delay
                self.rate_limit_wait_s += delay
                self._sleep(delay)
                continue

            if resp.status >= 500:
                if attempt > self.max_retries:
                    raise EnturHTTPError(resp.status, resp.text, url)
                delay = min(0.5 * (2 ** (attempt - 1)), 4.0)
                waited += delay
                self._sleep(delay)
                continue

            if resp.status != 200:
                record.elapsed_s = resp.elapsed_s
                raise EnturHTTPError(resp.status, resp.text, url)

            try:
                payload = json.loads(resp.text)
            except json.JSONDecodeError as exc:
                raise EnturProtocolError(
                    f"ugyldig JSON fra {operation}: {exc}; body={resp.text[:200]!r}"
                ) from exc

            data = self._validate(payload, operation)
            record.partial_errors = list(self.partial_errors)
            return data

    def _retry_delay(self, resp: HttpResponse, attempt: int) -> float:
        """429-forsinkelse: les rate-limit-expiry-time, ellers eksponentiell.

        Entur sender INGEN Retry-After (verifisert). Vi leser den likevel hvis
        den skulle dukke opp, som defensiv fallback - men den er ikke kravet.
        """
        expiry = resp.headers.get("rate-limit-expiry-time")
        delay = parse_rate_limit_expiry(expiry, now=self._clock())
        if delay is not None:
            # Vent til utløp, men aldri mer enn 65 s i prototypen.
            return min(delay + 0.05, 65.0)
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return min(0.5 * (2 ** (attempt - 1)), 8.0)

    def _validate(self, payload, operation: str) -> dict:
        if not isinstance(payload, dict):
            raise EnturProtocolError(f"{operation}: forventet JSON-objekt, fikk {type(payload)}")
        errors = payload.get("errors")
        self.last_errors = errors if isinstance(errors, list) else ([{"message": str(errors)}] if errors else [])

        # Geocoder v3 svarer GeoJSON (ingen `data`-konvolutt). Feil kommer som
        # HTTP 4xx eller `errors`/`fault`. Suksess krever `features`.
        if operation.startswith("geocoder"):
            if payload.get("fault"):
                raise EnturGraphQLError(
                    [{"message": json.dumps(payload.get("fault"), ensure_ascii=False)}]
                )
            if self.last_errors:
                raise EnturGraphQLError(self.last_errors)
            if "features" not in payload:
                raise EnturProtocolError(
                    f"{operation}: GeoJSON-svar mangler 'features' (nokler: {sorted(payload)[:6]})"
                )
            self.partial_errors = []
            return payload

        data = payload.get("data")
        if data is None:
            raise EnturGraphQLError(self.last_errors or [{"message": "data=null uten errors"}])

        if self.last_errors:
            # Partial errors: data finnes, men er ufullstendig. Kalleren maa
            # selv vurdere; vi eksponerer dem via client.partial_errors.
            self.partial_errors = self.last_errors
        else:
            self.partial_errors = []
        return data
