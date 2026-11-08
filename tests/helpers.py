"""Testhjelpere: konfigurasjon, fake Entur-klient, kjørende HTTP-server."""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

from app import server as server_module
from app.auth import hash_password
from app.config import Config
from app.db import Database
from app.pipeline import PipelineDeps
from prototype.geocoder import PlaceResolver

OSS = "KVE:TopographicPlace:31"


def make_config(tmpdir: str, validate: bool = True, **overrides) -> Config:
    values = dict(
        app_env="test",
        host="127.0.0.1",
        port=0,
        database_path=os.path.join(tmpdir, "app.db"),
        build_sha="testsha",
        public_base_url="http://127.0.0.1",
        cookie_secure=False,
        pseudonym_salt="test-pseudonym-salt-0123456789",
        session_secret="test-session-secret-0123456789abcdef",
        admin_user="admin",
        admin_password_hash=hash_password("correct horse battery", iterations=1000),
        health_entur_check=True,
        health_entur_cache_s=0,
        health_entur_timeout_s=1.0,
        conversation_ttl_minutes=30,
        rate_limit_per_hour=5,
        daily_sms_limit=10,
        simulate_require_auth=False,
    )
    values.update(overrides)
    config = Config(**values)
    if validate:
        config.validate()
    return config


def feature(place_id, name, county_id=OSS, layer="stopPlace", modes=None):
    return {
        "type": "Feature",
        "properties": {
            "id": place_id,
            "names": {"default": name},
            "layer": layer,
            "address": {
                "countyId": county_id,
                "county": "Østfold" if county_id == OSS else "Annet",
                "locality": "Test",
            },
            "transportModes": [{"mode": mode} for mode in (modes or ["bus"])],
            "stopPlaceTypes": ["onstreetBus"],
        },
    }


PLACE_IDS = {
    "skredderåsen": ("NSR:StopPlace:2636", "Skredderåsen", OSS),
    "skredderasen": ("NSR:StopPlace:2636", "Skredderåsen", OSS),
    "refsnes": ("NSR:StopPlace:3029", "Refsnes", OSS),
    "moss stasjon": ("NSR:StopPlace:58796", "Moss stasjon", OSS),
    "moss bussterminal": ("NSR:StopPlace:2900", "Moss bussterminal", OSS),
    "mysen": ("NSR:StopPlace:58797", "Mysen stasjon", OSS),
    "askim": ("NSR:StopPlace:58793", "Askim stasjon", OSS),
    "halden": ("NSR:StopPlace:2562", "Halden bussterminal", OSS),
    "fredrikstad": ("NSR:StopPlace:2306", "Fredrikstad bussterminal", OSS),
}

KNOWN_PLACES = {
    "NSR:StopPlace:2636": ("Skredderåsen", OSS),
    "NSR:StopPlace:3029": ("Refsnes", OSS),
    "NSR:StopPlace:58796": ("Moss stasjon", OSS),
    "NSR:StopPlace:2900": ("Moss bussterminal", OSS),
    "NSR:StopPlace:58797": ("Mysen stasjon", OSS),
    "NSR:StopPlace:58793": ("Askim stasjon", OSS),
    "NSR:StopPlace:2562": ("Halden bussterminal", OSS),
    "NSR:StopPlace:2306": ("Fredrikstad bussterminal", OSS),
    "NSR:StopPlace:127": ("Ski stasjon", "KVE:TopographicPlace:32"),
    "NSR:StopPlace:203": ("Moss stasjon", OSS),
    "NSR:StopPlace:226": ("Mysen stasjon", OSS),
}


def _quay(stop_id, name, public_code=""):
    return {
        "id": f"NSR:Quay:{stop_id.split(':')[-1]}",
        "publicCode": public_code,
        "stopPlace": {"id": stop_id, "name": name},
    }


def departure_call(line="22", direction="Kambo", start="2026-11-06T08:39:00+01:00",
                   realtime=False, expected=None, cancellation=False, quay_code=""):
    return {
        "aimedDepartureTime": start,
        "expectedDepartureTime": expected or start,
        "actualDepartureTime": None,
        "realtime": realtime,
        "predictionInaccurate": False,
        "cancellation": cancellation,
        "quay": {"id": "NSR:Quay:4602", "publicCode": quay_code, "name": "Skredderåsen"},
        "destinationDisplay": {"frontText": direction},
        "serviceJourney": {
            "id": "OST:ServiceJourney:test",
            "directionType": "outbound",
            "journeyPattern": {
                "line": {
                    "id": f"OST:Line:1_{line}",
                    "publicCode": line,
                    "name": "Testlinje",
                    "transportMode": "bus",
                }
            },
        },
        "situations": [],
    }


def departure_payload(stop_id="NSR:StopPlace:2636", name="Skredderåsen", calls=None):
    calls = calls if calls is not None else [
        departure_call(),
        departure_call(direction="Moss sentrum", start="2026-11-06T08:54:00+01:00"),
        departure_call(direction="Kambo", start="2026-11-06T09:24:00+01:00"),
    ]
    return {
        "stopPlace": {
            "id": stop_id,
            "name": name,
            "transportMode": ["bus"],
            "quays": [{"id": "NSR:Quay:4602", "publicCode": "", "name": name}],
            "estimatedCalls": calls,
        }
    }


def leg(mode="bus", line="22", start="2026-11-06T08:39:00+01:00", end="2026-11-06T08:48:00+01:00",
        from_id="NSR:StopPlace:2636", from_name="Skredderåsen",
        to_id="NSR:StopPlace:2900", to_name="Moss bussterminal",
        distance=4750.0, duration=540, realtime=False):
    return {
        "mode": mode,
        "transportSubmode": "localBus",
        "duration": duration,
        "distance": distance,
        "realtime": realtime,
        "aimedStartTime": start,
        "expectedStartTime": start,
        "aimedEndTime": end,
        "expectedEndTime": end,
        "line": (
            {"id": f"OST:Line:1_{line}", "publicCode": line, "name": "Testlinje", "transportMode": "bus"}
            if line
            else None
        ),
        "fromPlace": {
            "name": from_name,
            "latitude": 59.4,
            "longitude": 10.6,
            "quay": _quay(from_id, from_name),
        },
        "toPlace": {
            "name": to_name,
            "latitude": 59.4,
            "longitude": 10.6,
            "quay": _quay(to_id, to_name),
        },
        "situations": [],
    }


def trip_pattern(legs, start="2026-11-06T08:39:00+01:00", end="2026-11-06T09:03:00+01:00",
                 duration=1440, walk=0, waiting=120, distance=9327.0):
    return {
        "aimedStartTime": start,
        "expectedStartTime": start,
        "aimedEndTime": end,
        "expectedEndTime": end,
        "duration": duration,
        "walkTime": walk,
        "waitingTime": waiting,
        "distance": distance,
        "streetDistance": 0.0,
        "legs": legs,
    }


def trip_payload(patterns=None):
    if patterns is None:
        patterns = [
            trip_pattern(
                [
                    leg(),
                    leg(line="20", start="2026-11-06T08:50:00+01:00", end="2026-11-06T09:03:00+01:00",
                        from_id="NSR:StopPlace:2900", from_name="Moss bussterminal",
                        to_id="NSR:StopPlace:3029", to_name="Refsnes"),
                ]
            )
        ]
    return {"trip": {"tripPatterns": patterns, "routingErrors": []}}


def walk_trip_payload(walk_m=400.0, walk_s=300):
    return trip_payload(
        [
            trip_pattern(
                [
                    leg(mode="foot", line="", start="2026-11-06T08:30:00+01:00",
                        end="2026-11-06T08:39:00+01:00", from_id="NSR:StopPlace:2636",
                        from_name="Skredderåsen", to_id="NSR:StopPlace:2636",
                        to_name="Skredderåsen", distance=walk_m, duration=walk_s),
                    leg(),
                ],
                walk=walk_s,
            )
        ]
    )


def scope_trip_payload():
    """Reise via Ski stasjon (Akershus) - skal flagges."""
    return trip_payload(
        [
            trip_pattern(
                [
                    leg(line="RE20", start="2026-11-06T08:33:00+01:00", end="2026-11-06T08:55:00+01:00",
                        from_id="NSR:StopPlace:58796", from_name="Moss stasjon",
                        to_id="NSR:StopPlace:127", to_name="Ski stasjon", distance=20000.0),
                    leg(line="R22", start="2026-11-06T09:13:00+01:00", end="2026-11-06T09:56:00+01:00",
                        from_id="NSR:StopPlace:127", from_name="Ski stasjon",
                        to_id="NSR:StopPlace:58797", to_name="Mysen stasjon", distance=30000.0),
                ],
                start="2026-11-06T08:33:00+01:00",
                end="2026-11-06T09:56:00+01:00",
                duration=4980,
                waiting=1080,
            )
        ]
    )


class FakeEnturClient:
    def __init__(self, *, departure_payload_fn=None, trip_payload=None, exception=None):
        self.calls: list = []
        self.departure_payload_fn = departure_payload_fn or (lambda stop_id, name: departure_payload(stop_id, name))
        self.trip_payload = trip_payload if trip_payload is not None else trip_payload_default()
        self.exception = exception
        self.partial_errors: list = []
        self.requests: list = []

    def graphql(self, query, variables=None):
        variables = variables or {}
        self.requests.append({"query": query, "variables": variables})
        self.calls.append(SimpleNamespace(status=200))
        if self.exception is not None:
            raise self.exception
        if "estimatedCalls" in query:
            stop_id = variables.get("stopPlaceId", "")
            if stop_id not in KNOWN_PLACES:
                return {"stopPlace": None}
            name = KNOWN_PLACES[stop_id][0]
            return self.departure_payload_fn(stop_id, name)
        if "tripPatterns" in query:
            if variables.get("from") not in KNOWN_PLACES or variables.get("to") not in KNOWN_PLACES:
                return {
                    "trip": {
                        "tripPatterns": [],
                        "routingErrors": [{"code": "locationNotFound", "description": "ukjent"}],
                    }
                }
            return self.trip_payload
        raise AssertionError(f"ukjent query: {query[:80]}")

    def geocoder_autocomplete(self, params):
        self.calls.append(SimpleNamespace(status=200))
        query = (params.get("q") or "").strip().lower()
        self.requests.append({"params": params})
        if query in PLACE_IDS:
            place_id, name, county = PLACE_IDS[query]
            return {"type": "FeatureCollection", "features": [feature(place_id, name, county)]}
        if query == "oslo s":
            return {
                "type": "FeatureCollection",
                "features": [feature("NSR:StopPlace:337", "Oslo S", "KVE:TopographicPlace:03")],
            }
        return {"type": "FeatureCollection", "features": []}

    def geocoder_place(self, ids, lang="no"):
        self.calls.append(SimpleNamespace(status=200))
        self.requests.append({"ids": list(ids)})
        features = [
            feature(place_id, KNOWN_PLACES[place_id][0], KNOWN_PLACES[place_id][1])
            for place_id in ids
            if place_id in KNOWN_PLACES
        ]
        return {"type": "FeatureCollection", "features": features}


def trip_payload_default():
    return trip_payload()


def fake_probe_factory(state="OK"):
    def probe():
        if isinstance(state, Exception):
            raise state
        if state == "OK":
            return True, "fake ok"
        return False, "fake degraded"

    return probe


@dataclass
class HttpResult:
    status: int
    body: bytes
    headers: dict
    cookies: dict

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


class RunningApp:
    def __init__(self, tmpdir, config_overrides=None, *, client=None, probe=None,
                 inmobile_http_post=None, sms_adapter=None, now_fn=None, interpreter=None):
        self.tmpdir = tmpdir
        self.config = make_config(tmpdir, **(config_overrides or {}))
        self.client = client or FakeEnturClient()
        deps = PipelineDeps(
            client=self.client,
            resolver=PlaceResolver(self.client),
            thresholds=self.config.thresholds(),
        )
        self.ctx = server_module.create_app(
            self.config,
            deps=deps,
            entur_probe=probe or fake_probe_factory("OK"),
            inmobile_http_post=inmobile_http_post,
            sms_adapter=sms_adapter,
            now_fn=now_fn,
            interpreter=interpreter,
        )
        self.httpd = server_module.make_server(self.ctx, host="127.0.0.1", port=0)
        self.thread: threading.Thread | None = None
        self.host, self.port = self.httpd.server_address[0], self.httpd.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "RunningApp":
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True
        )
        self.thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                self.get("/healthz")
                return self
            except OSError:
                time.sleep(0.02)
        raise RuntimeError("server startet ikke")

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=5)

    # -- HTTP ------------------------------------------------------------
    def request(self, method, path, *, body=None, headers=None, cookies=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=15)
        request_headers = {"Host": f"{self.host}:{self.port}"}
        if headers:
            request_headers.update(headers)
        if cookies:
            request_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        header_map: dict[str, str] = {}
        set_cookies: list[str] = []
        for key, value in response.getheaders():
            header_map[key.lower()] = value
            if key.lower() == "set-cookie":
                set_cookies.append(value)
        new_cookies: dict[str, str] = {}
        for cookie in set_cookies:
            pair = cookie.split(";", 1)[0]
            if "=" in pair:
                key, _, value = pair.partition("=")
                new_cookies[key] = value
        result = HttpResult(response.status, payload, header_map, new_cookies)
        result.set_cookies = set_cookies  # type: ignore[attr-defined]
        connection.close()
        return result

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post_json(self, path, payload, **kwargs):
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        return self.request("POST", path, body=body, headers=headers, **kwargs)

    def post_form(self, path, form: dict, cookies=None, headers=None):
        from urllib.parse import urlencode

        request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            request_headers.update(headers)
        return self.request(
            "POST", path, body=urlencode(form).encode(), headers=request_headers, cookies=cookies
        )

    def login(self, username="admin", password="correct horse battery"):
        page = self.get("/admin")
        csrf = page.cookies.get("ob_csrf", "")
        csrf_field = _extract_csrf(page.text)
        response = self.post_form(
            "/admin/login",
            {"csrf": csrf_field or csrf, "username": username, "password": password},
            cookies=page.cookies,
        )
        cookies = dict(page.cookies)
        cookies.update(response.cookies)
        return response, cookies


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf" value="'
    start = html.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = html.find('"', start)
    return html[start:end]


def invite(database_path: str, **kwargs) -> Database:
    db = Database(database_path)
    db.init()
    return db
