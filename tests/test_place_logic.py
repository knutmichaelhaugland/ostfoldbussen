"""Stedsvalg: eksakt vinner, tvetydighet avklares, kontekst kan løse opp."""

import unittest

from app.place_logic import Candidate, choose_place, distance_km, format_clarification


def cand(cid, name, locality="", lat=None, lon=None):
    return Candidate(id=cid, name=name, locality=locality, lat=lat, lon=lon)


REFS = [
    cand("NSR:StopPlace:3029", "Refsnes", "Moss", 59.43, 10.63),
    cand("NSR:StopPlace:3025", "Refsneskrona", "Moss", 59.44, 10.64),
    cand("NSR:StopPlace:3012", "Refne", "Halden", 59.12, 11.38),
]
MOSS = [cand("NSR:StopPlace:58796", "Moss stasjon", "Moss"),
        cand("NSR:StopPlace:2900", "Moss bussterminal", "Moss"),
        cand("NSR:StopPlace:62468", "Moss næringspark", "Moss")]


class PlaceLogicTests(unittest.TestCase):
    def test_exact_name_wins_even_with_nearby_stops(self):
        decision = choose_place("Moss stasjon", MOSS)
        self.assertEqual(decision.decision, "exact")
        self.assertEqual(decision.chosen.id, "NSR:StopPlace:58796")

    def test_ambiguous_place_asks(self):
        decision = choose_place("Moss", MOSS)
        self.assertEqual(decision.decision, "clarify")
        self.assertEqual(len(decision.options), 3)
        text = format_clarification("Moss", decision)
        self.assertIn("Mente du", text)
        self.assertIn("Moss stasjon", text)

    def test_refsnes_exact_and_ambiguous(self):
        self.assertEqual(choose_place("Refsnes", REFS).decision, "exact")
        self.assertEqual(choose_place("Refsne", REFS).decision, "clarify")

    def test_single_candidate_is_accepted(self):
        decision = choose_place("Ørje", [cand("NSR:StopPlace:911", "Ørje busstorg")])
        self.assertEqual(decision.decision, "accept")

    def test_no_candidates_is_not_found(self):
        self.assertEqual(choose_place("Oslo S", []).decision, "not_found")

    def test_context_proximity_can_resolve_ambiguity(self):
        context = cand("ctx", "Moss bussterminal", "Moss", 59.43, 10.66)
        close = [cand("a", "Sentrum", "Moss", 59.44, 10.67),
                 cand("b", "Sentrum", "Fredrikstad", 59.21, 10.94)]
        decision = choose_place("Sentrum", close, context=context)
        self.assertEqual(decision.decision, "accept")
        self.assertEqual(decision.chosen.id, "a")

    def test_context_too_far_asks(self):
        context = cand("ctx", "Moss", "", 59.43, 10.66)
        far = [cand("a", "Sentrum", "Halden", 59.12, 11.38),
               cand("b", "Sentrum", "Sarpsborg", 59.28, 11.11)]
        self.assertEqual(choose_place("Sentrum", far, context=context).decision, "clarify")

    def test_distance(self):
        a = cand("a", "x", lat=59.0, lon=10.0)
        b = cand("b", "y", lat=60.0, lon=10.0)
        self.assertAlmostEqual(distance_km(a, b), 111.2, delta=1.0)
