"""Enhetstester for stedsoppslag med Østfold-ettervalidering og alias."""

import unittest

from prototype import config
from prototype.geocoder import PlaceResolver


def feature(place_id, name, layer="stopPlace", county_id="KVE:TopographicPlace:31", county="Østfold", modes=None):
    return {
        "type": "Feature",
        "properties": {
            "id": place_id,
            "names": {"default": name},
            "layer": layer,
            "address": {"countyId": county_id, "county": county, "locality": "Moss"},
            "transportModes": [{"mode": m} for m in (modes or ["bus"])],
            "stopPlaceTypes": ["onstreetBus"],
        },
    }


class FakeClient:
    def __init__(self, autocomplete=None, place=None):
        self.autocomplete = autocomplete or {}
        self.place = place or {}
        self.autocomplete_calls = []
        self.place_calls = []

    def geocoder_autocomplete(self, params):
        self.autocomplete_calls.append(params)
        return self.autocomplete

    def geocoder_place(self, ids, lang="no"):
        self.place_calls.append(list(ids))
        features = [
            self.place[place_id] for place_id in ids if place_id in self.place
        ]
        return {"type": "FeatureCollection", "features": features}


class ResolveTests(unittest.TestCase):
    def test_finds_ostfold_stop_place(self):
        client = FakeClient(
            autocomplete={
                "type": "FeatureCollection",
                "features": [feature("NSR:StopPlace:2636", "Skredderåsen")],
            }
        )
        res = PlaceResolver(client).resolve("Skredderåsen")
        self.assertTrue(res.found)
        self.assertEqual(res.hit.id, "NSR:StopPlace:2636")
        params = client.autocomplete_calls[0]
        self.assertEqual(params["counties"], config.OSTFOLD_COUNTY_ID)
        self.assertEqual(params["layers"], "stopPlace")
        self.assertEqual(params["q"], "Skredderåsen")

    def test_rejects_wrong_county_and_wrong_layer(self):
        client = FakeClient(
            autocomplete={
                "type": "FeatureCollection",
                "features": [
                    feature("NSR:StopPlace:3634", "Halden", county_id="KVE:TopographicPlace:32", county="Buskerud"),
                    feature("OSM:TopographicPlace:1", "Halden torg", layer="poi"),
                    feature("NSR:StopPlace:2562", "Halden bussterminal"),
                ],
            }
        )
        res = PlaceResolver(client).resolve("Halden")
        self.assertTrue(res.found)
        self.assertEqual(res.hit.id, "NSR:StopPlace:2562")
        self.assertEqual(len(res.rejected), 2)
        reasons = {r.reason for r in res.rejected}
        self.assertIn("countyId!=KVE:TopographicPlace:31", reasons)
        self.assertIn("layer!=stopPlace", reasons)

    def test_no_valid_candidate_returns_not_found(self):
        client = FakeClient(
            autocomplete={
                "type": "FeatureCollection",
                "features": [feature("NSR:StopPlace:337", "Oslo S", county_id="KVE:TopographicPlace:03", county="Oslo")],
            }
        )
        res = PlaceResolver(client).resolve("Oslo S")
        self.assertFalse(res.found)
        self.assertIsNone(res.hit)

    def test_alias_moss_sentrum_maps_to_bussterminal(self):
        verified = feature("NSR:StopPlace:2900", "Moss bussterminal", modes=["bus"])
        client = FakeClient(place={"NSR:StopPlace:2900": verified})
        res = PlaceResolver(client).resolve("Moss sentrum")
        self.assertTrue(res.found)
        self.assertTrue(res.alias_used)
        self.assertEqual(res.hit.id, "NSR:StopPlace:2900")
        self.assertIn("produktvalg", res.hit.source)
        self.assertEqual(client.autocomplete_calls, [])  # alias bruker /place, ikke søk

    def test_alias_unverified_still_returns_alias_with_note(self):
        client = FakeClient(place={})
        res = PlaceResolver(client).resolve("byen")
        self.assertTrue(res.found)
        self.assertTrue(res.alias_used)
        self.assertIn("kunne ikke verifiseres", res.alias_note)

    def test_ambiguous_first_candidate_is_marked(self):
        client = FakeClient(
            autocomplete={
                "type": "FeatureCollection",
                "features": [
                    feature("NSR:StopPlace:3029", "Refsnes"),
                    feature("NSR:StopPlace:3025", "Refsneskrona"),
                ],
            }
        )
        res = PlaceResolver(client).resolve("Refsne")
        self.assertTrue(res.found)
        self.assertTrue(res.ambiguous)
        self.assertEqual(res.hit.id, "NSR:StopPlace:3029")

    def test_counties_are_cached(self):
        client = FakeClient(
            place={"NSR:StopPlace:2636": feature("NSR:StopPlace:2636", "Skredderåsen")}
        )
        resolver = PlaceResolver(client)
        first = resolver.counties_of(["NSR:StopPlace:2636"])
        second = resolver.counties_of(["NSR:StopPlace:2636"])
        self.assertEqual(first, second)
        self.assertEqual(len(client.place_calls), 1)

    def test_unknown_id_gives_none_county(self):
        resolver = PlaceResolver(FakeClient(place={}))
        self.assertIsNone(resolver.county_of_stop_place("NSR:StopPlace:999999"))

    def test_fylke_filter_uses_counties_not_bbox(self):
        client = FakeClient(autocomplete={"features": []})
        PlaceResolver(client).resolve("Moss")
        params = client.autocomplete_calls[0]
        self.assertNotIn("bbox", params)


if __name__ == "__main__":
    unittest.main()
