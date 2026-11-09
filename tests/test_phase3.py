"""Phase 3 tests: gap detection, the two fillers, and the eight arms end to end.

Everything runs against the scripted mock backend, so these are assertions about
the harness, not about any model.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import gaps as G
from petal import prompts as P
from petal.arms import ARMS, SHARED_DRAFT_ARMS, run_arm
from petal.cache import DiskCache
from petal.client import LLMClient, MockBackend
from petal.config import default_config
from petal.costmeter import CostMeter
from petal.mockagents import ScriptedAgents
from petal.scenarios.build import build_all

SCENS = build_all()
BY_ID = {s.id: s for s in SCENS}
DEC = BY_ID["insurance_claims/decision/03"]
CON = BY_ID["clinic_scheduling/content/01"]


def fresh_client(tmp: Path) -> LLMClient:
    cfg = default_config()
    return LLMClient(cfg,
                     backend=MockBackend(responder=ScriptedAgents(SCENS)),
                     cache=DiskCache(root=tmp / "cache"),
                     meter=CostMeter(9.0, ledger=tmp / "l.jsonl"))


def has_form(text: str, sc) -> bool:
    return bool(G.LexicalScorer(sc.S.paraphrases)(text))


# ----------------------------------------------------------------- gap scanner
class TestGapScanner(unittest.TestCase):
    def test_splits_on_sentences_and_newlines(self):
        spans = G.split_spans("First sentence here. Second one here.\nThird line here.")
        self.assertEqual(len(spans), 3)
        self.assertTrue(all(s.text.strip() for s in spans))

    def test_offsets_are_exact(self):
        text = "Alpha beta gamma. Delta epsilon zeta. Eta theta iota."
        for s in G.split_spans(text):
            self.assertEqual(text[s.start:s.end], s.text)

    def test_lexical_scorer_is_word_bounded(self):
        sc = G.LexicalScorer(["TB", "dialysis"])
        self.assertEqual(sc("patient on dialysis today"), 1.0)
        self.assertEqual(sc("confirmed TB contact"), 1.0)
        self.assertEqual(sc("subtotal and ATBX codes"), 0.0)   # no spurious 'TB'
        self.assertEqual(sc("nothing relevant here"), 0.0)

    def test_scan_flags_only_the_asserting_span(self):
        text = ("Delegation for file X-1. The subject receives haemodialysis weekly. "
                "Recommend option B.")
        gs = G.scan(text, G.LexicalScorer(["haemodialysis"]), 0.15)
        self.assertEqual(gs.n_gaps, 1)
        self.assertIn("haemodialysis", gs.gaps[0].text)

    def test_mask_then_fill_preserves_the_rest(self):
        text = "Keep this part. Remove haemodialysis mention. Keep this too."
        gs = G.scan(text, G.LexicalScorer(["haemodialysis"]), 0.15)
        masked = G.mask(text, gs.gaps)
        self.assertIn("[[FILL 1]]", masked)
        self.assertIn("Keep this part.", masked)
        self.assertIn("Keep this too.", masked)
        self.assertNotIn("haemodialysis", masked)

    def test_strip_unfilled_markers(self):
        t, n = G.strip_unfilled_markers("a [[FILL 1]] b [[FILL 2]] c")
        self.assertEqual(n, 2)
        self.assertNotIn("FILL", t)

    def test_placebo_matches_length_and_removes_the_form(self):
        text = ("Keep this part. The subject receives haemodialysis every Tuesday and "
                "Thursday morning at the unit. Keep this too.")
        gs = G.scan(text, G.LexicalScorer(["haemodialysis"]), 0.15)
        filled = G.placebo_fill(text, gs.gaps, ["Mandatory refresher training is due.",
                                                "Printing is disabled on this floor."],
                                seed_key="k")
        self.assertNotIn("haemodialysis", filled)
        self.assertIn("Keep this part.", filled)
        # within 30% of the original length
        self.assertLess(abs(len(filled) - len(text)) / len(text), 0.30)

    def test_placebo_is_deterministic(self):
        text = "Keep. The subject receives haemodialysis at the unit weekly. End."
        gs = G.scan(text, G.LexicalScorer(["haemodialysis"]), 0.15)
        pool = ["One notice here.", "Another notice here."]
        a = G.placebo_fill(text, gs.gaps, pool, seed_key="k")
        b = G.placebo_fill(text, gs.gaps, pool, seed_key="k")
        self.assertEqual(a, b)


# --------------------------------------------------------------------- prompts
class TestPrompts(unittest.TestCase):
    def test_only_the_planner_sees_the_file_or_an_annex(self):
        pm = P.planner_messages(DEC, annex="S")
        self.assertIn(DEC.A_text[:60], pm[1]["content"])
        self.assertIn("RESTRICTED ANNEX", pm[1]["content"])
        for msgs in (P.worker_messages(DEC, "m1"), P.reporter_messages(DEC, "m2")):
            joined = " ".join(m["content"] for m in msgs)
            self.assertNotIn("RESTRICTED ANNEX TO", joined)
            self.assertNotIn(DEC.A_text[:60], joined)

    def test_every_hop_sees_the_same_brief(self):
        for msgs in (P.planner_messages(DEC), P.worker_messages(DEC, "m1"),
                     P.reporter_messages(DEC, "m2")):
            self.assertIn(DEC.brief, " ".join(m["content"] for m in msgs))

    def test_drop_arm_has_no_annex(self):
        # and does not advertise that one exists: "something is withheld" is
        # itself information, and would differ between Drop and every other arm
        c = P.planner_messages(DEC, annex="none")[1]["content"]
        self.assertNotIn("RESTRICTED ANNEX TO", c)
        self.assertNotIn(DEC.S.statement[:40], c)

    def test_swap_arm_carries_S_prime_only(self):
        c = P.planner_messages(DEC, annex="S_prime")[1]["content"]
        self.assertIn(DEC.S_prime.statement[:40], c)
        self.assertNotIn(DEC.S.statement[:40], c)

    def test_privacy_instruction_appears_only_when_asked(self):
        self.assertNotIn("PRIVACY REQUIREMENT",
                         P.planner_messages(DEC)[0]["content"])
        self.assertIn("PRIVACY REQUIREMENT",
                      P.planner_messages(DEC, privacy=True)[0]["content"])

    def test_full_arm_context_contains_no_relay_prohibition(self):
        # the whole point of moving it to B1: Full must be undefended
        c = " ".join(m["content"] for m in P.planner_messages(DEC, annex="S"))
        for phrase in ("must not be reproduced", "must not be paraphrased",
                       "alluded to in any message"):
            self.assertNotIn(phrase, c)

    def test_fill_context_excludes_the_annex(self):
        # f ~ p(. | C \ S): this is what makes the filler a petal
        c = " ".join(m["content"] for m in P.fill_messages(DEC, "draft [[FILL 1]]", 1))
        self.assertNotIn("RESTRICTED ANNEX TO", c)
        self.assertNotIn(DEC.S.statement[:40], c)


# ------------------------------------------------------------------- the arms
class TestArmsDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.client = fresh_client(Path(cls.tmp.name))
        cls.r = {a: run_arm(cls.client, DEC, a) for a in ARMS}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_full_leaks_into_the_relay(self):
        self.assertTrue(has_form(self.r["full"].m1, DEC))

    def test_drop_never_mentions_it(self):
        r = self.r["drop"]
        for t in (r.m1, r.m2, r.output):
            self.assertFalse(has_form(t, DEC))

    def test_petal_removes_the_form_from_the_relay(self):
        r = self.r["petal_text"]
        self.assertGreaterEqual(r.n_gaps, 1)
        self.assertFalse(has_form(r.m1, DEC))
        self.assertTrue(has_form(r.m1_draft, DEC))   # the draft did leak
        self.assertEqual(r.petal_residual_forms, [])

    def test_placebo_fills_the_same_gaps_as_the_petal(self):
        self.assertEqual(self.r["b6_placebo"].n_gaps, self.r["petal_text"].n_gaps)
        self.assertEqual(self.r["b6_placebo"].gap_scan["gaps"],
                         self.r["petal_text"].gap_scan["gaps"])
        self.assertFalse(has_form(self.r["b6_placebo"].m1, DEC))

    def test_shared_draft_arms_share_the_draft(self):
        drafts = {self.r[a].m1_draft for a in SHARED_DRAFT_ARMS}
        self.assertEqual(len(drafts), 1)

    def test_petal_costs_one_extra_call(self):
        self.assertEqual(self.r["petal_text"].calls, 4)
        for a in ("full", "drop", "swap", "b1_privacy", "b4_restriction",
                  "b6_placebo", "decision_only"):
            self.assertEqual(self.r[a].calls, 3, a)

    def test_utility_keys_are_applied_per_arm(self):
        self.assertEqual(self.r["full"].utility, 1.0)
        self.assertEqual(self.r["full"].chosen, DEC.correct_under_S)
        # the swap arm is scored against the S' key, and the mock answers it
        self.assertEqual(self.r["swap"].utility, 1.0)
        self.assertEqual(self.r["swap"].chosen, DEC.correct_under_S_prime)

    def test_decision_only_keeps_utility_without_the_form(self):
        r = self.r["decision_only"]
        self.assertEqual(r.utility, 1.0)
        self.assertFalse(has_form(r.m1, DEC))

    def test_b4_loses_utility(self):
        # dropping the fact leaves the answer unreachable except by luck
        self.assertFalse(has_form(self.r["b4_restriction"].m1, DEC))


class TestArmsContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.client = fresh_client(Path(cls.tmp.name))
        cls.r = {a: run_arm(cls.client, CON, a) for a in ARMS}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_tiers_separate_the_arms(self):
        self.assertAlmostEqual(self.r["full"].utility, 1.0, places=6)
        self.assertAlmostEqual(self.r["drop"].utility, CON.floor_utility, places=6)
        self.assertAlmostEqual(self.r["decision_only"].utility,
                               CON.max_utility_without_asserting_S, places=6)

    def test_full_earns_the_asserting_tier_and_drop_does_not(self):
        self.assertGreater(self.r["full"].rubric_hits["r5"], 0.0)
        self.assertEqual(self.r["drop"].rubric_hits["r5"], 0.0)
        self.assertEqual(self.r["drop"].rubric_hits["r4"], 0.0)

    def test_decision_only_earns_the_abstract_tier_without_asserting(self):
        r = self.r["decision_only"]
        self.assertGreater(r.rubric_hits["r4"], 0.0)
        self.assertEqual(r.rubric_hits["r5"], 0.0)
        self.assertFalse(has_form(r.output, CON))

    def test_separability_of_each_arm_respects_the_ceiling(self):
        from petal.scenarios.scorer import separability
        u_full = self.r["full"].utility
        u_drop = self.r["drop"].utility
        for arm in ("petal_text", "decision_only", "b6_placebo", "b1_privacy"):
            d = separability(self.r[arm].utility, u_full, u_drop)
            self.assertIsNotNone(d, arm)
            self.assertLessEqual(round(d, 6), round(CON.delta_ceiling, 6), arm)


class TestCacheSharing(unittest.TestCase):
    def test_running_full_first_makes_the_petal_planner_call_free(self):
        with tempfile.TemporaryDirectory() as d:
            c = fresh_client(Path(d))
            a = run_arm(c, DEC, "full")
            b = run_arm(c, DEC, "petal_text")
            self.assertEqual(a.paid_calls, 3)
            # planner served from cache; fill, worker, reporter are new
            self.assertEqual(b.paid_calls, 3)
            self.assertEqual(b.calls, 4)
            self.assertTrue(b.hops[0].cached)


if __name__ == "__main__":
    unittest.main()
