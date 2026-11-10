"""Phase 6 tests: paired statistics and the Experiment 1 aggregation."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import analysis as A
from petal.correction import Validation, bootstrap_corrected, cohens_kappa
from petal.stats import (bootstrap_delta, bootstrap_mean, bootstrap_paired_diff,
                         holm, mcnemar_exact, mde_delta, wilcoxon_paired)


class TestBootstrap(unittest.TestCase):
    def test_ci_brackets_the_mean(self):
        iv = bootstrap_mean([0.0, 1.0] * 20, n_boot=2000, seed=1)
        self.assertAlmostEqual(iv.point, 0.5)
        self.assertLess(iv.lo, 0.5)
        self.assertGreater(iv.hi, 0.5)

    def test_ci_narrows_with_n(self):
        a = bootstrap_mean([0.0, 1.0] * 10, n_boot=2000, seed=1)
        b = bootstrap_mean([0.0, 1.0] * 200, n_boot=2000, seed=1)
        self.assertLess(b.hi - b.lo, a.hi - a.lo)

    def test_constant_sample_has_zero_width(self):
        iv = bootstrap_mean([0.3] * 30, n_boot=500, seed=0)
        self.assertAlmostEqual(iv.lo, 0.3)
        self.assertAlmostEqual(iv.hi, 0.3)

    def test_paired_diff_uses_pairing(self):
        # perfectly correlated inputs: every difference is exactly 0.2, so the
        # paired CI must have zero width even though each arm varies a lot
        a = [0.1, 0.5, 0.9, 0.3]
        b = [x - 0.2 for x in a]
        iv = bootstrap_paired_diff(a, b, n_boot=1000, seed=0)
        self.assertAlmostEqual(iv.point, 0.2)
        self.assertAlmostEqual(iv.hi - iv.lo, 0.0, places=9)

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            bootstrap_paired_diff([1, 2, 3], [1, 2])


class TestDelta(unittest.TestCase):
    def test_point_estimate(self):
        arm = [0.6] * 10
        full = [1.0] * 10
        drop = [0.2] * 10
        iv = bootstrap_delta(arm, full, drop, n_boot=500, seed=0)
        self.assertAlmostEqual(iv.point, 0.5)

    def test_nan_when_S_made_no_difference(self):
        iv = bootstrap_delta([0.5] * 8, [0.4] * 8, [0.4] * 8, n_boot=200, seed=0)
        self.assertNotEqual(iv.point, iv.point)       # NaN

    def test_can_exceed_one_and_go_negative(self):
        hi = bootstrap_delta([1.2] * 6, [1.0] * 6, [0.0] * 6, n_boot=200, seed=0)
        lo = bootstrap_delta([-0.1] * 6, [1.0] * 6, [0.0] * 6, n_boot=200, seed=0)
        self.assertGreater(hi.point, 1.0)
        self.assertLess(lo.point, 0.0)

    def test_ratio_of_means_survives_zero_denominators_per_scenario(self):
        # two of four scenarios have U_full == U_drop; a mean of per-scenario
        # ratios would divide by zero or silently drop them
        arm = [0.5, 0.5, 0.9, 0.1]
        full = [0.5, 0.5, 1.0, 1.0]
        drop = [0.5, 0.5, 0.0, 0.0]
        iv = bootstrap_delta(arm, full, drop, n_boot=500, seed=0)
        self.assertEqual(iv.point, iv.point)
        self.assertAlmostEqual(iv.point, (0.5 - 0.25) / (0.75 - 0.25))


class TestMcNemar(unittest.TestCase):
    def test_no_discordant_pairs(self):
        r = mcnemar_exact([True, False], [True, False])
        self.assertEqual(r["n_discordant"], 0)
        self.assertEqual(r["p_value"], 1.0)

    def test_counts_discordant_correctly(self):
        a = [True, True, False, False]
        b = [False, True, False, True]
        r = mcnemar_exact(a, b)
        self.assertEqual((r["b"], r["c"]), (1, 1))

    def test_strongly_one_sided_is_significant(self):
        a = [True] * 12 + [False] * 8
        b = [False] * 12 + [False] * 8
        r = mcnemar_exact(a, b)
        self.assertEqual(r["b"], 12)
        self.assertEqual(r["c"], 0)
        self.assertLess(r["p_value"], 0.001)


class TestWilcoxonAndHolm(unittest.TestCase):
    def test_identical_arms(self):
        r = wilcoxon_paired([0.3] * 10, [0.3] * 10)
        self.assertEqual(r["p_value"], 1.0)

    def test_consistent_shift_is_significant(self):
        a = [0.1 * i for i in range(12)]
        b = [x - 0.25 for x in a]
        self.assertLess(wilcoxon_paired(a, b)["p_value"], 0.01)

    def test_holm_orders_and_scales(self):
        out = holm({"a": 0.001, "b": 0.02, "c": 0.4})
        self.assertAlmostEqual(out["a"]["p_adj"], 0.003)
        self.assertAlmostEqual(out["b"]["p_adj"], 0.04)
        self.assertAlmostEqual(out["c"]["p_adj"], 0.4)
        self.assertTrue(out["a"]["reject"])
        self.assertTrue(out["b"]["reject"])
        self.assertFalse(out["c"]["reject"])

    def test_holm_is_monotone(self):
        out = holm({"a": 0.03, "b": 0.031, "c": 0.032})
        adj = [out[k]["p_adj"] for k in ("a", "b", "c")]
        self.assertEqual(adj, sorted(adj))

    def test_holm_never_exceeds_one(self):
        out = holm({k: 0.9 for k in "abcde"})
        self.assertTrue(all(v["p_adj"] <= 1.0 for v in out.values()))


class TestPower(unittest.TestCase):
    def test_mde_shrinks_with_n(self):
        a = mde_delta(0.3, 30, 1.0, 0.33)
        b = mde_delta(0.3, 300, 1.0, 0.33)
        self.assertLess(b, a)

    def test_mde_is_on_the_delta_scale(self):
        # the same utility sd over a narrower (U_full - U_drop) gap implies a
        # larger detectable delta
        wide = mde_delta(0.3, 30, 1.0, 0.0)
        narrow = mde_delta(0.3, 30, 1.0, 0.7)
        self.assertGreater(narrow, wide)


class TestRoganGladen(unittest.TestCase):
    def test_perfect_detector_is_identity(self):
        val = Validation(tp=50, fp=0, fn=0, tn=50)
        cr = bootstrap_corrected([True] * 30 + [False] * 70, val, n_boot=500, seed=0)
        self.assertAlmostEqual(cr.corrected, 0.30, places=6)

    def test_false_positives_pull_the_rate_down(self):
        # Se 1.0, Sp 0.8: an observed 0.30 overstates the truth
        val = Validation(tp=50, fp=10, fn=0, tn=40)
        cr = bootstrap_corrected([True] * 30 + [False] * 70, val, n_boot=500, seed=0)
        self.assertLess(cr.corrected, 0.30)

    def test_kappa(self):
        self.assertAlmostEqual(cohens_kappa([True, False] * 10,
                                            [True, False] * 10), 1.0)
        self.assertLess(cohens_kappa([True] * 10 + [False] * 10,
                                     [False] * 10 + [True] * 10), 0.0)


class TestPanelAggregation(unittest.TestCase):
    """Lambda must be the rate of asserting S under both conditions."""

    def _write(self, tmp: Path):
        runs, dets = [], []
        for i in range(6):
            sid = "d/decision/%02d" % i
            for arm, util, leak_s, leak_sp in [
                    ("full", 1.0, True, False),
                    ("swap", 1.0, False, True),
                    ("drop", 0.33, False, False),
                    ("petal_text", 1.0, False, False)]:
                runs.append({"scenario_id": sid, "use_type": "decision",
                             "domain": "d", "arm": arm, "model_role": "agent_a",
                             "seed": 1, "utility": util,
                             "hops": [{"role": "worker", "prompt_tokens": 100}]})
                targets = [("S", leak_s)]
                if arm == "swap":
                    targets.append(("S_prime", leak_sp))
                for label, lk in targets:
                    dets.append({"scenario_id": sid, "use_type": "decision",
                                 "arm": arm, "model_role": "agent_a", "seed": 1,
                                 "channel": "m1", "leak": lk, "target": label})
        rp, dp = tmp / "r.jsonl", tmp / "d.jsonl"
        rp.write_text("\n".join(json.dumps(r) for r in runs), encoding="utf-8")
        dp.write_text("\n".join(json.dumps(d) for d in dets), encoding="utf-8")
        return rp, dp

    def test_lambda_floor_and_control(self):
        with tempfile.TemporaryDirectory() as d:
            rp, dp = self._write(Path(d))
            panels, meta = A.load([rp], [dp])
            p = panels["decision"]
            self.assertEqual(meta["n_runs"], 24)
            self.assertAlmostEqual(A.leak_rate(p, "full"), 1.0)
            self.assertAlmostEqual(A.leak_rate(p, "swap"), 0.0)
            self.assertAlmostEqual(A.lambda_causal(p), 1.0)
            self.assertAlmostEqual(A.phi_floor(p), 0.0)
            # the swap arm did relay S', so its zero rate on S means something
            self.assertAlmostEqual(A.swap_control(p), 1.0)

    def test_delta_table(self):
        with tempfile.TemporaryDirectory() as d:
            rp, dp = self._write(Path(d))
            p = A.load([rp], [dp])[0]["decision"]
            dt = A.delta_table(p, ["petal_text"], n_boot=300)
            self.assertAlmostEqual(dt["petal_text"].point, 1.0)

    def test_decision_rule_reports_margin_and_ci(self):
        with tempfile.TemporaryDirectory() as d:
            rp, dp = self._write(Path(d))
            p = A.load([rp], [dp])[0]["decision"]
            r = A.decision_rule(p, kappa=2.0, lam=0.02, baseline="drop")
            self.assertTrue(r["available"])
            self.assertAlmostEqual(r["delta_utility"]["point"], 1.0 - 0.33)
            self.assertTrue(r["petal_wins"])
            self.assertIn("wins_at_ci_low", r)


if __name__ == "__main__":
    unittest.main()
