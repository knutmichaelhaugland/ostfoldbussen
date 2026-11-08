"""Entur-gateway: app-spesifikk konfigurasjon rundt prototype.entur_client.

Vi gjenbruker prototype.entur_client (prototypekontrakt) uendret og overstyrer kun
endepunkter/timeout via subklasse. prototype/ skal ikke endres på disk.
"""

from __future__ import annotations

import urllib.parse

from prototype import config as proto_config
from prototype.entur_client import EnturClient


class AppEnturClient(EnturClient):
    def __init__(self, config):
        super().__init__(
            client_name=config.entur_client_name,
            timeout=config.entur_timeout_s,
            max_retries=config.entur_max_retries,
        )
        self.journey_url = config.entur_journey_url
        base = config.entur_geocoder_url.rstrip("/")
        self.geocoder_autocomplete_url = base + "/autocomplete"
        self.geocoder_place_url = base + "/place"

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        import json

        payload: dict = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        body = json.dumps(payload).encode("utf-8")
        headers = dict(self.base_headers)
        headers["Content-Type"] = "application/json"
        return self._request_with_backoff(
            "POST", self.journey_url, headers, body, operation="graphql"
        )

    def geocoder_autocomplete(self, params: dict) -> dict:
        url = self.geocoder_autocomplete_url + "?" + urllib.parse.urlencode(params)
        return self._request_with_backoff(
            "GET", url, dict(self.base_headers), None, operation="geocoder-autocomplete"
        )

    def geocoder_place(self, ids: list[str], lang: str = "no") -> dict:
        params = {"ids": ",".join(ids), "lang": lang}
        url = self.geocoder_place_url + "?" + urllib.parse.urlencode(params)
        return self._request_with_backoff(
            "GET", url, dict(self.base_headers), None, operation="geocoder-place"
        )


def prototype_defaults_are_unchanged() -> bool:
    """Sanity: appen skal ikke ha mutert prototype.config ved import."""
    return (
        proto_config.ET_CLIENT_NAME == "ostfoldbussen-selfhosted"
        and proto_config.JOURNEY_PLANNER_URL
        == "https://api.entur.io/journey-planner/v3/graphql"
    )
