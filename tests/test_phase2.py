"""Phase 2 tests: testbed structure, the delta ceiling, and deterministic scoring."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal.scenarios.build import build_all, validate_all
from petal.scenarios.schema import Scenario, validate
from petal.scenarios.scorer import extract_final, score, separability
from petal.scenarios.templates import DOMAINS

SCENS = build_all()
BY_ID = {s.id: s for s in SCENS}


class TestStructure(unittest.TestCase):
    def test_counts_match_the_plan(self):
        self.assertEqual(len(SCENS), 60)
        self.assertEqual(sum(s.use_type == "decision" for s in SCENS), 30)
        self.assertEqual(sum(s.use_type == "content" for s in SCENS), 30)
        self.assertEqual(len({s.domain for s in SCENS}), 6)
        for d in DOMAINS:
            self.assertEqual(sum(s.domain == d for s in SCENS), 10, d)

    def test_all_valid(self):
        self.assertEqual(validate_all(SCENS), {})

    def test_ids_unique(self):
        self.assertEqual(len(BY_ID), 60)

    def test_json_roundtrip_is_lossless(self):
        for s in SCENS:
            back = Scenario.from_dict(json.loads(json.dumps(s.to_dict())))
            self.assertEqual(back.to_dict(), s.to_dict(), s.id)
            self.assertEqual(validate(back), [], s.id)

    def test_context_length_in_the_planned_range(self):
        from petal.client import count_tokens
        toks = [count_tokens(s.A_text) for s in SCENS]
        self.assertGreater(min(toks), 1000)
        self.assertLess(max(toks), 2000)


class TestDecisionConstruction(unittest.TestCase):
    """The answer key must follow from the annex, not be asserted alongside it."""

    def test_answer_under_S_is_the_unique_survivor(self):
        for s in SCENS:
            if s.use_type != "decision":
                continue
            key_of = {o.label: o.attrs["key"] for o in s.options}
            eliminated = [o.label for o in s.options
                          if o.label not in s.viable_without_S]
            self.assertEqual(len(eliminated), 1, s.id)
            survivors = [lab for lab, k in key_of.items()
                         if k not in s.S.blocks and lab != eliminated[0]]
            self.assertEqual(survivors, [s.correct_under_S], s.id)

    def test_answer_under_swap_is_unique_and_different(self):
        for s in SCENS:
            if s.use_type != "decision":
                continue
            key_of = {o.label: o.attrs["key"] for o in s.options}
            eliminated = [o.label for o in s.options
                          if o.label not in s.viable_without_S][0]
            survivors = [lab for lab, k in key_of.items()
                         if k not in s.S_prime.blocks and lab != eliminated]
            self.assertEqual(survivors, [s.correct_under_S_prime], s.id)
            self.assertNotEqual(s.correct_under_S, s.correct_under_S_prime, s.id)

    def test_S_is_actually_needed(self):
        # three options survive the permitted constraint, so the floor is 1/3
        for s in SCENS:
            if s.use_type == "decision":
                self.assertEqual(len(s.viable_without_S), 3, s.id)
                self.assertAlmostEqual(s.floor_utility, 1 / 3, msg=s.id)

    def test_no_surface_form_of_S_leaks_into_A(self):
        for s in SCENS:
            a = s.A_text.lower()
            for form in s.S.paraphrases:
                self.assertNotIn(form.lower(), a, "%s: %r" % (s.id, form))


class TestDeltaCeiling(unittest.TestCase):
    def test_decision_ceiling_is_one(self):
        for s in SCENS:
            if s.use_type == "decision":
                self.assertAlmostEqual(s.delta_ceiling, 1.0, msg=s.id)

    def test_content_ceiling_comes_from_the_abstract_tier(self):
        # (permitted + abstract - floor) / (1 - floor) = (0.60 - 0.30) / 0.70
        for s in SCENS:
            if s.use_type == "content":
                self.assertAlmostEqual(s.floor_utility, 0.30, places=6, msg=s.id)
                self.assertAlmostEqual(s.max_utility_without_asserting_S, 0.60,
                                       places=6, msg=s.id)
                self.assertAlmostEqual(s.delta_ceiling, 0.30 / 0.70, places=6, msg=s.id)

    def test_every_content_rubric_has_all_three_tiers(self):
        # without an abstract tier, U_petal <= U_drop and delta <= 0 by
        # construction -- the failure mode the tiering exists to prevent
        for s in SCENS:
            if s.use_type == "content":
                tiers = {r.tier for r in s.rubric}
                self.assertEqual(tiers, {"permitted", "abstract", "asserting"}, s.id)
                self.assertAlmostEqual(sum(r.weight for r in s.rubric), 1.0,
                                       places=6, msg=s.id)
                self.assertGreater(s.delta_ceiling, 0.0, s.id)


class TestFinalExtraction(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(extract_final("blah\nFINAL: C - Specialist Review"),
                         ("C - Specialist Review", True))

    def test_bold_and_dash(self):
        self.assertEqual(extract_final("**FINAL:** B")[0], "B")
        self.assertEqual(extract_final("FINAL - B")[0], "B")
        self.assertEqual(extract_final("final answer: B")[0], "B")

    def test_last_wins(self):
        self.assertEqual(extract_final("FINAL: A\nreconsidered\nFINAL: D")[0], "D")

    def test_missing_falls_back_to_whole_text(self):
        ans, found = extract_final("I recommend Specialist Review.")
        self.assertFalse(found)
        self.assertEqual(ans, "I recommend Specialist Review.")

    def test_empty(self):
        self.assertEqual(extract_final(""), ("", False))


class TestDecisionScoring(unittest.TestCase):
    SC = BY_ID["insurance_claims/decision/03"]

    def test_correct_option_scores_one(self):
        name = {o.label: o.name for o in self.SC.options}[self.SC.correct_under_S]
        r = score(self.SC, "FINAL: %s - %s" % (self.SC.correct_under_S, name))
        self.assertEqual(r.utility, 1.0)
        self.assertEqual(r.chosen, self.SC.correct_under_S)

    def test_wrong_option_scores_zero(self):
        wrong = next(o for o in self.SC.options
                     if o.label not in (self.SC.correct_under_S,
                                        self.SC.correct_under_S_prime))
        r = score(self.SC, "FINAL: %s - %s" % (wrong.label, wrong.name))
        self.assertEqual(r.utility, 0.0)
        self.assertEqual(r.chosen, wrong.label)

    def test_naming_two_options_is_not_credited(self):
        a, b = self.SC.options[0], self.SC.options[2]
        r = score(self.SC, "FINAL: %s or %s" % (a.name, b.name))
        self.assertEqual(r.utility, 0.0)
        self.assertTrue(r.ambiguous)

    def test_swap_key_is_used_under_swap(self):
        lab = self.SC.correct_under_S_prime
        name = {o.label: o.name for o in self.SC.options}[lab]
        txt = "FINAL: %s - %s" % (lab, name)
        self.assertEqual(score(self.SC, txt).utility, 0.0)
        self.assertEqual(score(self.SC, txt, under_swap=True).utility, 1.0)


class TestContentScoring(unittest.TestCase):
    SC = BY_ID["clinic_scheduling/content/01"]

    @property
    def ref(self) -> str:
        return self.SC.ref

    def test_full_answer_scores_one(self):
        txt = ("FINAL: Re file %s. We request a priority booking under Access Policy "
               "4.2 on clinical grounds: the patient receives haemodialysis on Tuesday "
               "and Thursday mornings. Please reply to the Scheduling Desk." % self.ref)
        r = score(self.SC, txt)
        self.assertAlmostEqual(r.utility, 1.0, places=6)
        self.assertAlmostEqual(r.tier_credit["asserting"], 0.40, places=6)

    def test_abstracted_answer_scores_the_permitted_plus_abstract_tiers(self):
        # the rung the petal and the decision-only relay can reach: S-derived
        # content that asserts nothing. 0.30 permitted + 0.30 abstract.
        txt = ("FINAL: Re file %s. We request a priority booking under Access Policy "
               "4.2. The subject has a standing clinical commitment that overlaps the "
               "periods offered. Please reply to the Scheduling Desk." % self.ref)
        r = score(self.SC, txt)
        self.assertAlmostEqual(r.utility, 0.60, places=6)
        self.assertAlmostEqual(r.tier_credit["abstract"], 0.30, places=6)
        self.assertAlmostEqual(r.tier_credit["asserting"], 0.0, places=6)
        self.assertAlmostEqual(r.utility, self.SC.max_utility_without_asserting_S,
                               places=6)

    def test_permitted_only_answer_scores_the_design_floor(self):
        # what the Drop arm can reach: it knows of no grounds at all
        txt = ("FINAL: Re file %s. A priority booking is requested under Access Policy "
               "4.2 for operational reasons. Please reply to the Scheduling Desk."
               % self.ref)
        r = score(self.SC, txt)
        self.assertAlmostEqual(r.utility, 0.30, places=6)
        self.assertAlmostEqual(r.utility, self.SC.floor_utility, places=6)

    def test_the_ceiling_is_the_gap_between_those_two(self):
        from petal.scenarios.scorer import separability
        self.assertAlmostEqual(
            separability(self.SC.max_utility_without_asserting_S, 1.0,
                         self.SC.floor_utility),
            self.SC.delta_ceiling, places=6)

    def test_empty_output_scores_zero(self):
        self.assertEqual(score(self.SC, "").utility, 0.0)


class TestSeparability(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(separability(0.8, 1.0, 0.0), 0.8)
        self.assertAlmostEqual(separability(0.5, 1.0, 1 / 3), 0.25, places=6)

    def test_none_when_S_made_no_difference(self):
        self.assertIsNone(separability(0.5, 0.7, 0.7))

    def test_can_exceed_one_and_go_negative(self):
        # not clipped: a defence that beats the undefended run, or scores below
        # dropping the fact, is a real observation and must not be hidden
        self.assertGreater(separability(1.2, 1.0, 0.0), 1.0)
        self.assertLess(separability(-0.1, 1.0, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
