"""Phase 5 tests: the ladder's arithmetic, its composition, and the probe bounds."""
from __future__ import annotations

import random
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal.chain import rewrite_slot
from petal.ladder import (AREA_OF, DROPPED, PLACEHOLDER_TRUE, Ladder, Rung,
                          all_categories, build_ladder, category_for, coarsen,
                          emit, true_value_at, watched_forms)
from petal.probe import (MatchProbe, binary_entropy, chance_error,
                         error_upper_ci, fano_mi_lower)


class TestRungArithmetic(unittest.TestCase):
    """Against the worked example in PETAL_v2 section 4.3."""

    #: exact coefficients; the paper displays these rounded as .79/.63/.40/.20
    PAPER = [(20, 0.8, 0.7894736842), (5, 0.7, 0.625), (3, 0.6, 0.4), (2, 0.6, 0.2)]

    def test_dobrushin_matches_the_paper(self):
        for k, p, eta in self.PAPER:
            self.assertAlmostEqual(Rung("r", k, p).eta, eta, places=6,
                                   msg="k=%d p=%.1f" % (k, p))

    def test_paper_product(self):
        lad = Ladder([Rung("r%d" % i, k, p) for i, (k, p, _) in
                      enumerate(self.PAPER)])
        # the paper quotes 0.039
        self.assertAlmostEqual(lad.eta_product(), 0.0395, places=3)

    def test_ldp_level(self):
        # eps = ln(p(k-1)/(1-p)); k=20, p=0.8 -> ln(76)
        import math
        self.assertAlmostEqual(Rung("r", 20, 0.8).epsilon, math.log(76), places=6)

    def test_dropped_rung_carries_nothing(self):
        r = Rung("dropped", 1, 1.0, [])
        self.assertEqual(r.eta, 0.0)
        self.assertEqual(r.transmit("anything", random.Random(0)), (DROPPED, False))

    def test_eta_product_excludes_dropped_by_default(self):
        lad = Ladder([Rung("a", 4, 0.7, ["1", "2", "3", "4"]),
                      Rung("dropped", 1, 1.0, [])])
        self.assertGreater(lad.eta_product(), 0.0)
        self.assertEqual(lad.eta_product(include_dropped=True), 0.0)

    def test_eta_rises_with_k(self):
        # a bigger alphabet contracts less for the same keep probability, which
        # is why the testbed's real alphabets must be used rather than the
        # paper's illustrative ones
        self.assertLess(Rung("a", 3, 0.8).eta, Rung("a", 30, 0.8).eta)


class TestRandomisedResponse(unittest.TestCase):
    def test_keeps_the_true_symbol_at_about_p(self):
        r = Rung("a", 5, 0.7, list("ABCDE"))
        rng = random.Random(1)
        kept = sum(r.transmit("A", rng)[1] for _ in range(4000))
        self.assertAlmostEqual(kept / 4000, 0.7, delta=0.03)

    def test_errors_are_uniform_over_the_others(self):
        r = Rung("a", 5, 0.5, list("ABCDE"))
        rng = random.Random(2)
        wrong = Counter(v for v, kept in
                        (r.transmit("A", rng) for _ in range(8000)) if not kept)
        self.assertEqual(set(wrong), set("BCDE"))
        for c in "BCDE":
            self.assertAlmostEqual(wrong[c] / sum(wrong.values()), 0.25, delta=0.04)

    def test_output_is_always_in_the_alphabet(self):
        r = Rung("a", 4, 0.6, list("WXYZ"))
        rng = random.Random(3)
        for _ in range(200):
            self.assertIn(r.transmit("W", rng)[0], list("WXYZ"))


class TestLadderFromTestbed(unittest.TestCase):
    LAD = build_ladder("medical")

    def test_every_category_has_an_area(self):
        self.assertEqual(set(all_categories()) - set(AREA_OF), set())

    def test_alphabets_come_from_the_testbed(self):
        names = [r.name for r in self.LAD.rungs]
        self.assertEqual(names, ["exact", "area", "kind", "placeholder", "dropped"])
        self.assertGreater(self.LAD.rungs[0].k, 15)
        self.assertEqual(self.LAD.rungs[3].k, 2)

    def test_category_lookup_resolves_every_proposition(self):
        for cat in all_categories().values():
            prop = cat["proposition"].format(name="The subject")
            self.assertIsNotNone(category_for(prop), cat["key"])

    def test_shared_propositions_are_benign(self):
        """Three restricted facts appear in two domains each.

        The lookup is therefore ambiguous. That is only harmless if the sharing
        categories coarsen identically, so assert it rather than assume it: if a
        future edit gave them different areas, the ladder would silently emit the
        wrong rung-1 symbol for one of them.
        """
        from petal.ladder import shared_proposition_groups
        groups = shared_proposition_groups()
        self.assertTrue(groups, "expected some shared propositions")
        cats = all_categories()
        for prop, keys in groups.items():
            kinds = {cats[k]["kind"] for k in keys}
            areas = {AREA_OF[k] for k in keys}
            self.assertEqual(len(kinds), 1, "%s: kinds %s" % (keys, kinds))
            self.assertEqual(len(areas), 1, "%s: areas %s" % (keys, areas))

    def test_bound_at_hop_is_the_running_product(self):
        e = [r.eta for r in self.LAD.rungs]
        self.assertAlmostEqual(self.LAD.bound_at_hop(1), e[0])
        self.assertAlmostEqual(self.LAD.bound_at_hop(2), e[0] * e[1])
        self.assertAlmostEqual(self.LAD.bound_at_hop(4), e[0] * e[1] * e[2] * e[3])

    def test_watched_forms_cover_every_rung(self):
        f = watched_forms(self.LAD, ["dialysis"])
        self.assertIn("dialysis", f)
        self.assertIn(PLACEHOLDER_TRUE, f)
        self.assertIn(self.LAD.rungs[1].alphabet[0], f)


class TestComposition(unittest.TestCase):
    """The ladder must coarsen the previous *emitted* value, not the original S.

    If it re-coarsened the true S each hop, the hops would be conditionally
    independent given S rather than a Markov chain, and T3's product bound would
    not apply -- only the single rung's eta would.
    """
    LAD = build_ladder("medical")
    CAT = all_categories()["dialysis"]

    def test_coarsening_follows_the_emitted_value_not_the_truth(self):
        wrong = all_categories()["chemo"]["proposition"].format(name="The subject")
        got = coarsen(wrong, self.LAD.rungs[1], "medical")
        self.assertEqual(got, AREA_OF["chemo"])
        self.assertNotEqual(got, AREA_OF["dialysis"])

    def test_coarsening_an_empty_slot_stays_empty(self):
        self.assertEqual(coarsen("", self.LAD.rungs[1], "medical"), DROPPED)

    def test_emit_threads_the_previous_value(self):
        rng = random.Random(0)
        wrong = all_categories()["chemo"]["proposition"].format(name="The subject")
        em = emit("deterministic", self.LAD, self.CAT, 2, rng,
                  prev_value=wrong, kind="medical")
        self.assertEqual(em.value, AREA_OF["chemo"])
        self.assertFalse(em.truthful)        # it is the wrong condition's area

    def test_deterministic_is_truthful_when_fed_the_truth(self):
        rng = random.Random(0)
        exact = true_value_at(self.CAT, self.LAD.rungs[0])
        em = emit("deterministic", self.LAD, self.CAT, 2, rng,
                  prev_value=exact, kind="medical")
        self.assertEqual(em.value, AREA_OF["dialysis"])
        self.assertTrue(em.truthful)

    def test_deterministic_rungs_have_coefficient_one(self):
        # errata item 5: a non-constant deterministic map does not contract
        rng = random.Random(0)
        for hop in (1, 2, 3, 4):
            em = emit("deterministic", self.LAD, self.CAT, hop, rng,
                      prev_value=None, kind="medical")
            self.assertEqual(em.eta_bound, 1.0, "hop %d" % hop)

    def test_none_schedule_never_decays(self):
        rng = random.Random(0)
        exact = true_value_at(self.CAT, self.LAD.rungs[0])
        for hop in range(1, 6):
            em = emit("none", self.LAD, self.CAT, hop, rng, prev_value="anything")
            self.assertEqual(em.value, exact)
            self.assertTrue(em.truthful)

    def test_random_dropout_stays_dropped(self):
        rng = random.Random(7)
        prev = ""
        em = emit("random_dropout", self.LAD, self.CAT, 2, rng,
                  prev_value=prev, kind="medical")
        self.assertEqual(em.value, DROPPED)

    def test_stochastic_reaches_the_placeholder_rung_by_hop_four(self):
        rng = random.Random(11)
        prev = None
        vals = []
        for hop in range(1, 5):
            em = emit("stochastic", self.LAD, self.CAT, hop, rng,
                      prev_value=prev, kind="medical")
            prev = em.value
            vals.append(em.rung)
        self.assertEqual(vals, ["exact", "area", "kind", "placeholder"])


class TestSlotRewrite(unittest.TestCase):
    FORMS = ["haemodialysis", "a kidney condition", PLACEHOLDER_TRUE]

    def test_replaces_the_slot_in_place(self):
        t = "Handover.\nThe subject receives haemodialysis weekly.\nRecommend option B."
        out, n = rewrite_slot(t, self.FORMS, "a kidney condition")
        self.assertEqual(n, 1)
        self.assertNotIn("haemodialysis", out)
        self.assertIn("a kidney condition", out)
        self.assertIn("Recommend option B.", out)

    def test_removes_further_occurrences(self):
        t = ("A. The subject receives haemodialysis.\n"
             "B. Again, haemodialysis is relevant.\nC. Done.")
        out, n = rewrite_slot(t, self.FORMS, "a kidney condition")
        self.assertEqual(n, 2)
        self.assertEqual(out.count("a kidney condition"), 1)
        self.assertNotIn("haemodialysis", out)

    def test_appends_when_the_agent_dropped_the_note(self):
        # a hop that forgot to carry the note must not be scored as a hop that
        # transmitted nothing -- that would flatter the decay
        out, n = rewrite_slot("Handover. Nothing relevant here.", self.FORMS,
                              "a kidney condition")
        self.assertEqual(n, 0)
        self.assertIn("a kidney condition", out)

    def test_dropped_value_removes_the_slot_entirely(self):
        t = "A. The subject receives haemodialysis.\nB. Done."
        out, n = rewrite_slot(t, self.FORMS, DROPPED)
        self.assertEqual(n, 1)
        self.assertNotIn("haemodialysis", out)
        self.assertNotIn("CARRIED NOTE", out)


class TestFano(unittest.TestCase):
    def test_zero_error_gives_full_entropy(self):
        self.assertAlmostEqual(fano_mi_lower(0.0, 23), 4.5236, places=3)

    def test_monotone_decreasing_below_chance(self):
        vals = [fano_mi_lower(e, 23) for e in (0.0, 0.1, 0.3, 0.6, 0.9)]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_at_or_above_chance_is_zero(self):
        # the algebra returns 0.065 bits at e=1.0 for k=23; an empty slot must
        # not put a floor under every decay curve
        k = 23
        self.assertEqual(fano_mi_lower(chance_error(k), k), 0.0)
        self.assertEqual(fano_mi_lower(1.0, k), 0.0)

    def test_binary_entropy_endpoints(self):
        self.assertEqual(binary_entropy(0.0), 0.0)
        self.assertEqual(binary_entropy(1.0), 0.0)
        self.assertAlmostEqual(binary_entropy(0.5), 1.0)

    def test_error_ci_is_wide_at_n_20(self):
        hi = error_upper_ci(0, 20)
        self.assertGreater(hi, 0.10)      # zero errors of 20 is not error 0
        self.assertLess(hi, 0.20)
        self.assertEqual(error_upper_ci(20, 20), 1.0)

    def test_conservative_bound_is_below_the_point_estimate(self):
        p = MatchProbe(["alpha one", "beta two", "gamma three", "delta four"])
        r = p.evaluate(["alpha one"] * 4, [0, 0, 0, 0])
        self.assertEqual(r.error_rate, 0.0)
        self.assertLess(r.mi_lower_bits_conservative, r.mi_lower_bits)


class TestMatchProbe(unittest.TestCase):
    CANDS = ["The subject receives haemodialysis treatment.",
             "The subject is receiving chemotherapy.",
             "The subject has epilepsy.",
             "The subject is pregnant."]

    def test_recovers_an_exact_slot(self):
        p = MatchProbe(self.CANDS)
        r = p.evaluate(["CARRIED NOTE: " + self.CANDS[2]], [2])
        self.assertEqual(r.error_rate, 0.0)

    def test_empty_text_counts_as_an_error(self):
        p = MatchProbe(self.CANDS)
        r = p.evaluate(["", "   "], [0, 1])
        self.assertEqual(r.error_rate, 1.0)
        self.assertEqual(r.mi_lower_bits, 0.0)

    def test_coarse_slot_does_not_identify_the_category(self):
        p = MatchProbe(self.CANDS)
        r = p.evaluate(["CARRIED NOTE: a standing clinical commitment"] * 4,
                       [0, 1, 2, 3])
        # one of the four may match by chance; three cannot
        self.assertGreaterEqual(r.error_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
