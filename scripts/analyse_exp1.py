"""Experiment 1 analysis: writes results/exp1.md.

  py -3.12 scripts/analyse_exp1.py --runs runs/exp1_*.jsonl
  py -3.12 scripts/analyse_exp1.py --runs R --labels data/labels/sheet_X.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal import analysis as A
from petal import paths
from petal.config import Config, default_config
from petal.labelling import read_sheet, validation_from_sheet

PAIRS = [("petal_text", "b6_placebo"), ("petal_text", "b1_privacy"),
         ("petal_text", "b4_restriction"), ("decision_only", "b4_restriction"),
         # H5/H6: the relay-granularity gradient, fixed in
         # results/prefreeze_rule.md before the arm was run
         ("constraint_only", "decision_only"), ("constraint_only", "full")]
DELTA_ARMS = ["petal_text", "constraint_only", "decision_only", "b6_placebo",
              "b1_privacy", "b4_restriction"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--detections", nargs="*", default=None)
    ap.add_argument("--labels", default="", help="hand-label sheet for Rogan-Gladen")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cfg = Config.load() if paths.CONFIG.exists() else default_config()
    runs = [p for pat in args.runs for p in sorted(glob.glob(pat))] or args.runs
    dets = ([p for pat in args.detections for p in sorted(glob.glob(pat))]
            if args.detections else
            [str(r).replace(".jsonl", "") + "_detections.jsonl" for r in runs])

    scen_index = A.scenario_index()
    panels, meta = A.load(runs, dets, scenarios=scen_index)
    all_runs = [json.loads(l) for r in runs
                for l in Path(r).read_text(encoding="utf-8").splitlines() if l.strip()]
    val = None
    val_note = ("No hand-labelled validation set supplied, so leak rates are "
                "**observed, not corrected**. PETAL_v2 errata item 1: an observed "
                "rate is not a lower bound once the detector has false positives, "
                "and this one has them. Run `scripts/label.py` and pass `--labels`.")
    if args.labels:
        try:
            val = validation_from_sheet(read_sheet(Path(args.labels)))
            val_note = ("Validation set: n=%d, Se=%.3f, Sp=%.3f, Youden=%.3f."
                        % (val.n, val.sensitivity, val.specificity, val.youden))
        except (OSError, ValueError) as e:
            val_note = "Could not use %s: %s" % (args.labels, e)

    L = ["# Experiment 1: disclosure-use separability", "",
         "Runs: %s" % ", ".join("`%s`" % Path(r).name for r in runs),
         "%d runs, %d detections, models %s, seeds %s."
         % (meta["n_runs"], meta["n_detections"], meta["models"], meta["seeds"]),
         "", "Every comparison is scenario-paired; the bootstrap resamples "
         "scenarios, not runs.", ""]

    # --- provenance: was the testbed frozen, and how were gaps found? -----
    from petal import prereg
    pre = prereg.load()
    L += ["## Provenance", ""]
    if pre is None:
        L.append("**No pre-registration.** The testbed was not frozen before these "
                 "runs, so nothing rules out scenario fixes made after seeing the "
                 "results, which would be selection on the outcome. See "
                 "`petal/prereg.py`.")
    else:
        same = prereg.current_scenarios_sha() == pre.scenarios_sha256
        L.append("Testbed frozen %s at `%s` (%d scenarios, git `%s`), audited on "
                 "`%s`. scenarios.json %s the frozen hash."
                 % (pre.created_utc, pre.scenarios_sha256[:12], pre.n_scenarios,
                    (pre.git.get("commit") or "?")[:8], pre.audit_model,
                    "matches" if same else "**NO LONGER MATCHES**"))
        L += ["", "Exclusion rule, fixed before the run: %s" % pre.exclusion_rule]
        for n in pre.notes:
            L.append("- re-freeze: %s" % n)
    scorers = sorted({r.get("gap_scan", {}).get("scorer") for r in all_runs
                      if r.get("gap_scan")} - {None})
    miss = sum(r.get("gap_scores_missing", 0) for r in all_runs)
    if scorers:
        L += ["", "Petal gap scan: %s%s." % (
            ", ".join("`%s`" % s for s in scorers),
            "; %d spans had no entailment score and were treated as clean" % miss
            if miss else "")]
        if any(s == "lexical" for s in scorers):
            L.append("")
            L.append("**This is the lexical-gap petal.** Gaps were found by surface "
                     "form while leaks are scored by entailment, so a paraphrase the "
                     "form list does not cover passes the petal unmasked and is then "
                     "counted against it. The petal's leak rate here is an upper "
                     "bound on the mechanism and its delta a lower bound; the "
                     "entailment-backed pass is `scripts/emit_gap_pairs.py`.")
    L += ["", "## Detector validation", "", val_note, ""]

    out_json: dict = {"meta": meta, "use_types": {}}

    for ut, p in panels.items():
        L += ["---", "", "## %s-type tasks (n = %d scenarios)"
              % (ut.capitalize(), len(p.scenarios)), ""]

        L += ["### Utility and leak by arm", "",
              "Leak is on the `%s` channel: the relay a defence is responsible "
              "for. `m1_draft` is the planner's pre-defence output, shown so the "
              "petal's effect on the channel is visible separately from any "
              "downstream dilution." % A.PRIMARY_CHANNEL, "",
              "| arm | utility | leak m1_draft | leak m1 | leak m2 | leak output |",
              "|---|---|---|---|---|---|"]
        for arm in p.arms():
            from petal.stats import bootstrap_mean
            u = bootstrap_mean(p.utility[arm])
            cells = []
            for ch in A.CHANNELS:
                r = A.leak_rate(p, arm, ch)
                cells.append("-" if r != r else "%.3f" % r)
            L.append("| %s | %s | %s |" % (arm, u, " | ".join(cells)))
        L.append("")

        lam = A.lambda_causal(p)
        flo = A.phi_floor(p)
        L += ["- **Causal leak** Lambda = leak(full) - leak(swap) = **%s**"
              % ("n/a" if lam != lam else "%.3f" % lam),
              "- **Inference floor** Phi_floor = leak(drop) = **%s**"
              % ("n/a" if flo != flo else "%.3f" % flo),
              "- *Positive control*: the Swap arm asserts **S'** at %s. If this "
              "were near zero the arm relayed nothing and its low rate on S "
              "would show specificity that was never tested."
              % ("n/a" if A.swap_control(p) != A.swap_control(p)
                 else "%.3f" % A.swap_control(p)),
              "", "Both terms of Lambda are the rate of asserting *S*. The second "
              "is measured where S is absent, so it is the rate of asserting S "
              "anyway -- detector false positives plus confabulation -- and "
              "subtracting it is what separates a causal leak from an artefact. "
              "Only Lambda is what a relay defence can act on; the floor is "
              "unavoidable by any relay design and is subtracted, not charged to "
              "the defence.", ""]

        # --- delta -------------------------------------------------------
        dt = A.delta_table(p, DELTA_ARMS, n_boot=cfg.n_bootstrap, seed=cfg.seed)
        cl = A.ceiling(p, n_boot=cfg.n_bootstrap, seed=cfg.seed)
        dn = A.delta_normalised_table(p, DELTA_ARMS, n_boot=cfg.n_bootstrap,
                                      seed=cfg.seed)
        design_ceiling = (sum(p.u_max_no_s) / len(p.u_max_no_s)
                          if A.has_ceiling(p) else None)

        L += ["### Separability delta", "",
              "delta = (U_arm - U_drop) / (U_full - U_drop), as a ratio of means "
              "over scenario-paired bootstrap resamples. A ratio of means, not a "
              "mean of ratios: per scenario the denominator is often 0 and "
              "averaging per-scenario ratios would drop exactly the scenarios "
              "that carry no information about delta.", ""]
        if cl is not None:
            L += ["**Ceiling, on delta's own scale: %s.** A perfect non-asserting "
                  "answer scores %.3f here on average (decision tasks: 1.0, since "
                  "choosing correctly asserts nothing; content tasks: the permitted "
                  "plus abstract tiers). Pushed through the identical estimator, "
                  "that is the delta such an answer would earn."
                  % (cl, design_ceiling or float("nan")), "",
                  "This is *not* the `delta_ceiling` the scenario schema publishes. "
                  "That one is normalised by the chance floor and a perfect 1.0, "
                  "both design quantities; this one by the Drop and Full arms' "
                  "measured utilities, as delta is. The two scales differ whenever "
                  "U_drop != chance or U_full != 1.0, which is always, so dividing "
                  "a measured delta by the schema's number misstates how much of "
                  "the available room an arm reached.", "",
                  "**delta / ceiling is the headline.** It is resampled as one "
                  "quantity -- (U_arm - U_drop) / (U_maxNoS - U_drop), the "
                  "(U_full - U_drop) cancelling -- rather than divided after the "
                  "fact, so its CI accounts for the two terms sharing scenarios. "
                  "1.0 means the arm reached everything available to a defence "
                  "that never asserts S. It is the only figure comparable across "
                  "use types, and so the one Conjecture C1 is read from.", ""]
        L += ["| arm | delta [95% CI] | delta / ceiling [95% CI] |", "|---|---|---|"]
        for arm, iv in dt.items():
            nv = dn.get(arm)
            L.append("| %s | %s | %s |" % (arm, iv, nv if nv is not None else "-"))
        L.append("")

        # --- decision rule ----------------------------------------------
        L += ["### Decision rule (PETAL_v2 §4.2.4)", "",
              "Petal wins iff dU > kappa x dLeak + lambda x dLength, against the "
              "restriction-aware relay. Length is the relay's tokens as a "
              "fraction of the Full arm's, so lambda is dimensionless.", "",
              "| kappa | dU [95% CI] | dLeak | dLength | threshold | petal wins? "
              "| wins at CI low? |", "|---|---|---|---|---|---|---|"]
        for kap in [cfg.kappa] + list(cfg.kappa_sensitivity):
            d = A.decision_rule(p, kappa=kap, lam=cfg.lambda_length)
            if not d.get("available"):
                continue
            du = d["delta_utility"]
            L.append("| %.1f | %.3f [%.3f, %.3f] | %+.3f | %+.3f | %+.3f | %s | %s |"
                     % (kap, du["point"], du["lo"], du["hi"], d["delta_leak"],
                        d["delta_length_frac"], d["threshold"],
                        "yes" if d["petal_wins"] else "no",
                        "yes" if d["wins_at_ci_low"] else "no"))
        L.append("")

        # --- corrected rates --------------------------------------------
        if val is not None:
            L += ["### Corrected leak rates (Rogan-Gladen)", "",
                  "CIs resample the trace set *and* the validation set; holding "
                  "Se and Sp fixed gives intervals that are too narrow.", "",
                  "| arm | observed | corrected [95% CI] |", "|---|---|---|"]
            for arm, row in A.corrected_leaks(p, val, n_boot=cfg.n_bootstrap,
                                              seed=cfg.seed).items():
                if "corrected" in row:
                    L.append("| %s | %.3f | %.3f [%.3f, %.3f] |"
                             % (arm, row["observed"], row["corrected"],
                                row["lo"], row["hi"]))
                else:
                    L.append("| %s | %.3f | %s |"
                             % (arm, row["observed"],
                                row.get("corrected_error", "n/a")))
            L.append("")

        # --- tests -------------------------------------------------------
        t = A.paired_tests(p, PAIRS)
        L += ["### Paired tests, Holm-corrected", "",
              "One Holm family per use type, covering leak *and* utility tests "
              "together: the paper reads them as one claim about whether the petal "
              "helps, so correcting them separately would understate the "
              "correction.", "",
              "**Petal vs B6 placebo is a leak comparison, not a utility one.** On "
              "decision tasks the two arms are expected to tie on utility by "
              "construction: both fill the same spans of the same draft, and the "
              "decision itself lives in the part of the draft neither of them "
              "masks. A null there is the design working, not a finding. What the "
              "placebo controls for is whether merely *occupying* the slot changes "
              "the leak rate, so the leak row of that pair is the one to read.", "",
              "| test | p | p (Holm) | reject at 0.05 |", "|---|---|---|---|"]
        for name, r in sorted(t["holm"].items()):
            L.append("| %s | %s | %s | %s |"
                     % (name,
                        "n/a" if r["p"] is None or r["p"] != r["p"] else "%.4f" % r["p"],
                        "n/a" if r["p_adj"] != r["p_adj"] else "%.4f" % r["p_adj"],
                        "yes" if r["reject"] else "no"))
        L.append("")

        # --- decision-implied leakage ------------------------------------
        if ut == "decision":
            from petal import implied as IM
            chosen: dict[str, list[str]] = {}
            for r in all_runs:
                if r.get("arm") in ("decision_only", "petal_text") and r.get("chosen"):
                    chosen.setdefault(r["scenario_id"], []).append(r["chosen"])
            by_arm: dict[str, dict[str, list[str]]] = {}
            for r in all_runs:
                if r.get("use_type") == "decision" and r.get("chosen"):
                    by_arm.setdefault(r["arm"], {}).setdefault(
                        r["scenario_id"], []).append(r["chosen"])
            scen_list = list(scen_index.values())
            arm_inf = IM.per_arm_leakage(scen_list, by_arm)
            relay_m = IM.relay_leakage(all_runs, scen_list)
            relay_x = IM.relay_leakage_exact(all_runs, scen_list)
            out_json["use_types"][ut] = out_json["use_types"].get(ut, {})
            ils = {pr: IM.analyse(scen_list, chosen=chosen, prior=pr)
                   for pr in IM.PRIORS}
            il = ils["uninformed"]
            ga = ils["generator_aware"]
            out_json["decision_implied_leakage"] = {k: v.to_dict()
                                                    for k, v in ils.items()}
            L += ["### Decision-implied leakage", "",
                  "A decision scenario is built so that S changes the answer -- that "
                  "is what lets the Swap arm show the agent *used* S. The cost is "
                  "that the answer is then a function of S, so the answer itself "
                  "carries information about S. Which options were ruled out narrows "
                  "the restricted category down, whatever the relay says.", "",
                  "So on decision tasks there is a floor no relay-level defence can "
                  "go below while still getting the task right. It is not "
                  "Phi_floor, which is what an agent asserts with S absent; this "
                  "survives a perfect defence, a perfect detector, and an agent that "
                  "emits nothing but the chosen option. It is also outside Theorem "
                  "T2, whose slack bound assumes S is independent of the output Y -- "
                  "here Y is chosen *because* of S.", "",
                  "Computed exactly from the generator, not probed: each category "
                  "bars two of four options and a permitted constraint removes a "
                  "third, so the posterior over categories given the answer has a "
                  "closed form. It is computed per scenario and then averaged. "
                  "Pooling scenarios, or pooling domains, would credit the "
                  "adversary's uncertainty with things they can read straight off "
                  "the case file -- which domain it is, and which option the "
                  "service-level constraint removed.", "",
                  "Two adversaries, because the gap between them is the finding:", "",
                  "- **uninformed** -- knows the case file and the domain's list of "
                  "restricted categories, nothing more.",
                  "- **generator-aware** -- also knows that a scenario's restricted "
                  "category always leaves exactly one viable option, because the "
                  "construction is published in this paper. Categories that would "
                  "leave two are then not candidates at all.", "",
                  "| quantity | uninformed | generator-aware |", "|---|---|---|",
                  "| **I(constraint; S)**, what `constraint_only` relays | "
                  "**%.3f bits** | **%.3f bits** |"
                  % (IM.analyse(scen_list, prior="uninformed",
                                observable="constraint").mutual_information_bits,
                     IM.analyse(scen_list, prior="generator_aware",
                                observable="constraint").mutual_information_bits),
                  "| candidate categories | %d | %d |"
                  % (il.k_categories, ga.k_categories),
                  "| H(S) | %.3f bits | %.3f bits |"
                  % (il.prior_entropy_bits, ga.prior_entropy_bits),
                  "| H(S \\| answer) | %.3f bits | %.3f bits |"
                  % (il.conditional_entropy_bits, ga.conditional_entropy_bits),
                  "| **I(answer; S)** | **%.3f bits** | **%.3f bits** |"
                  % (il.mutual_information_bits, ga.mutual_information_bits),
                  "| H(answer) -- the hard cap on I | %.3f bits | %.3f bits |"
                  % (il.answer_entropy_bits, ga.answer_entropy_bits),
                  "| fraction of S implied by the answer | **%.1f%%** | **%.1f%%** |"
                  % (100 * il.fraction_of_secret, 100 * ga.fraction_of_secret),
                  "| adversary names the category | %.3f | %.3f |"
                  % (il.map_recovery, ga.map_recovery),
                  "| chance | %.3f | %.3f |"
                  % (il.chance_recovery, ga.chance_recovery)]
            if il.empirical_n:
                L.append("| from answers the models actually gave (n=%d) | %.3f | "
                         "%.3f |" % (il.empirical_n, il.empirical_recovery,
                                     ga.empirical_recovery))
            if il.empirical_n:
                L += ["", "Note the empirical row sits near the generator-aware "
                      "column under *both* priors. The uninformed adversary's MAP "
                      "figure of %.3f is an average over answers that an ambiguous "
                      "category could have produced -- but the builder never picks "
                      "an ambiguous category, so no such answer is ever actually "
                      "seen. On the answers the models really gave, even the "
                      "uninformed adversary recovers S at %.3f. The uninformed "
                      "column is a floor on a case that does not arise; the "
                      "generator-aware column is what the testbed does."
                      % (il.map_recovery, il.empirical_recovery)]
            L += ["", "| domain | I, uninformed | I, generator-aware | "
                  "recovery, generator-aware |", "|---|---|---|---|"]
            for d in sorted(il.per_domain):
                a, b = il.per_domain[d], ga.per_domain[d]
                L.append("| %s | %.3f | %.3f | %.3f vs %.3f chance |"
                         % (d, a["mutual_information_bits"],
                            b["mutual_information_bits"], b["map_recovery"],
                            b["chance_recovery"]))
            L += ["",
                  "To the generator-aware adversary the answer carries **%.3f bits, "
                  "%.1f%% of H(S)**, naming the right category %.0f%% of the time "
                  "against a %.0f%% chance baseline."
                  % (ga.mutual_information_bits, 100 * ga.fraction_of_secret,
                     100 * ga.map_recovery, 100 * ga.chance_recovery), "",
                  "**Read the bits, not only the percentage.** I(answer; S) cannot "
                  "exceed H(answer) = %.3f bits, because that is all a choice among "
                  "three viable options can carry. The percentage is that cap "
                  "divided by H(S), so it is a statement about how large the "
                  "restricted alphabet is, not about how leaky the answer is. "
                  "Against a domain's full 12-category pool the same answer is "
                  "%.1f%% of the secret; against a pool of three it would be ~100%%. "
                  "The bits are the invariant."
                  % (ga.answer_entropy_bits, 100 * il.fraction_of_secret), "",
                  "**And this is a property of this testbed, not of decision tasks "
                  "in general.** Each bar-pair here carries two conditions "
                  "(`petal/scenarios/confusable.py`), so H(S | answer) = %.3f bits "
                  "of genuine residual uncertainty. An earlier build had one "
                  "condition per pair, H(S | answer) = 0.03 bits and %.0f%% of S "
                  "implied -- the answer named the category almost uniquely, and "
                  "the decision-only arm could not have failed. A deployment whose "
                  "restricted facts map many-to-one onto decisions leaks a smaller "
                  "share than this; one whose facts map one-to-one leaks more. The "
                  "number is reported as this testbed's, scoped."
                  % (ga.conditional_entropy_bits, 97.9), "",
                  "#### Two leakage axes, and why one is not enough", "",
                  "The relay detector scores **assertion**. A relay that says "
                  "\"Option B\" entails nothing about dialysis, so an arm that "
                  "relays only its conclusion reads as near-zero leakage on every "
                  "table above while handing over most of S. Reporting assertion "
                  "leakage alone would make exactly the claim this section exists "
                  "to refute, so the inferential axis is reported per arm, from the "
                  "answers each arm actually gave. Bits are Fano on the measured "
                  "recovery rate -- a lower bound valid for any adversary, and it "
                  "correctly bounds a guessing arm at 0 rather than crediting it "
                  "with the sharp-but-wrong posterior a plug-in entropy would.", "",
                  "| arm | utility | assertion leak (m1) | recovers S from the "
                  "relay | bits (LB) | recovers S from the answer |",
                  "|---|---|---|---|---|---|"]
            for arm in sorted(arm_inf,
                              key=lambda a: -A._mean(p.utility.get(a, [0.0]))):
                lk = A.leak_rate(p, arm)
                rm = relay_m.get(arm) or {}
                L.append("| %s | %.3f | %s | %s | %s | %.3f |"
                         % (arm, A._mean(p.utility.get(arm, [float("nan")])),
                            "-" if lk != lk else "%.3f" % lk,
                            "-" if not rm else "%.3f" % rm["recovery"],
                            "-" if not rm else "%.3f" % rm["mi_lower_bits"],
                            arm_inf[arm]["recovery"]))
            grad = {o: IM.analyse(scen_list, prior="generator_aware",
                                  observable=o) for o in IM.OBSERVABLES}
            naive = {o: IM.analyse(scen_list, prior="uninformed", observable=o)
                     for o in IM.OBSERVABLES}
            L += ["", "#### The relay-granularity gradient (H7)", "",
                  "Computed exactly from the generator, under the "
                  "**generator-aware** adversary. That is the true I(relay; S) "
                  "here: the scenarios are drawn from the generator's own "
                  "distribution, so mutual information under any other prior "
                  "describes what a mistaken adversary believes rather than what "
                  "leaks. The uninformed column is carried alongside, labelled as "
                  "exactly that.", "",
                  "| relay | carries | I(relay; S) | H(S \\| relay) | adversary "
                  "recovers | naive adversary believes |",
                  "|---|---|---|---|---|---|"]
            for arm, obs, what in [("full", "reason", "the reason"),
                                   ("constraint_only", "constraint",
                                    "the constraint"),
                                   ("decision_only", "answer", "the conclusion")]:
                g = grad[obs]
                L.append("| `%s` | %s | **%.3f bits** | **%.3f** | %.3f | %.3f bits |"
                         % (arm, what, g.mutual_information_bits,
                            g.conditional_entropy_bits, g.map_recovery,
                            naive[obs].mutual_information_bits))
            L += ["",
                  "**Disclosure drops from reason to constraint, then stays flat "
                  "from constraint to conclusion.** Relaying the constraint keeps "
                  "%.3f bit hidden -- which of the conditions sharing a barred pair "
                  "applies -- that relaying the reason gives away entirely. It is no "
                  "better than relaying the bare conclusion, and no worse, while "
                  "leaving the choice with the Worker. That is a point *for* "
                  "constraint relays." % grad["constraint"].conditional_entropy_bits,
                  "", "#### How much more do real relays disclose? (H8)", "",
                  "The figures above assume the relay carries *only* what its arm "
                  "is named for. A real `constraint_only` relay may write "
                  "\"unavailable Tuesday and Thursday mornings due to ongoing "
                  "treatment\" -- a partial reason the assertion detector can score "
                  "clean while it narrows S further. So the computed value is a "
                  "**floor**, and the measured one is what an adversary reading the "
                  "relay text actually recovers.", "",
                  "| arm | computed floor | names a condition | certainty "
                  "gained (bits) | about the true S (bits) | recovers S | "
                  "learned adversary (bits, LB) |",
                  "|---|---|---|---|---|---|---|"]
            for arm, obs in [("full", "reason"), ("constraint_only", "constraint"),
                             ("decision_only", "answer"), ("petal_text", None),
                             ("b6_placebo", None), ("b4_restriction", None),
                             ("b1_privacy", None), ("drop", None), ("swap", None)]:
                x = relay_x.get(arm)
                if not x:
                    continue
                m = relay_m.get(arm) or {}
                floor = ("%.3f bits" % grad[obs].mutual_information_bits) if obs else "-"
                L.append("| %s | %s | %.3f | %.3f | **%.3f** | %.3f | %.3f |"
                         % (arm, floor, x["names_condition"], x["mi_bits"],
                            x["mi_about_true_s_bits"], x["recovery"],
                            m.get("mi_lower_bits", float("nan"))))
            L += ["", "**Disclosed (bits) is the headline.** The relay is read for "
                  "what it names -- a condition, by surface form -- and the exact "
                  "posterior is applied: naming a condition identifies it; naming "
                  "none leaves the adversary with what the answer implies, measured "
                  "per arm rather than assumed.", "",
                  "**The last column is not the headline and must not be read as "
                  "one.** It is a TF-IDF ranker over the candidate propositions: a "
                  "*learned* adversary, limited by having a handful of scenarios to "
                  "generalise from. It reports 0 bits for `decision_only`, where the "
                  "true figure is %.3f, because it cannot learn that \"option B\" "
                  "means a particular barred pair -- and the Clopper-Pearson bound "
                  "then correctly rounds a weak probe down to nothing. Taken as the "
                  "result it would say every arm but `full` leaks exactly zero, "
                  "which is the opposite of H7. It is kept as a valid lower bound "
                  "from one concrete attacker, and nothing more."
                  % grad["answer"].mutual_information_bits, "",
                  "`disclosed` and `recovers S` come apart on exactly one arm. The "
                  "first is disclosure to an adversary who *believes* the relay, the "
                  "second how often they are then right about S. On `swap` the relay "
                  "names S', so a believing adversary's uncertainty collapses while "
                  "their accuracy is zero -- which is what the Swap control exists "
                  "to show. Everywhere else the relay is truthful about S and the "
                  "two agree.", "",
                  "Both remain lower bounds in a stated way: a partial reason the "
                  "surface-form list does not cover -- \"due to ongoing treatment\" "
                  "-- narrows S further and is counted by neither. That gap is H8, "
                  "and an LLM adversary reading the permitted file alongside the "
                  "relay is what would measure it.", "",
                  "This is measured on **`m1`, the relay**, not on the final answer. "
                  "An earlier version read the answer, which made every arm that got "
                  "the task right score identically -- the Full arm, which states "
                  "the restricted fact verbatim, came out level with "
                  "`decision_only`, which states only which option to book. That "
                  "left the inferential axis unable to separate the arms, which was "
                  "the reason for having it.", ""]
            out_json["relay_gradient"] = {
                "generator_aware": {o: g.to_dict() for o, g in grad.items()},
                "uninformed": {o: g.to_dict() for o, g in naive.items()},
                "measured_on_relay": relay_m}

            L += ["", "The last two columns answer different questions and must not "
                  "be read as one. **Recovery from the relay** is what the defence "
                  "is responsible for, and the defended arms drive it to chance "
                  "(%.3f). **Recovery from the answer** is what the task output "
                  "implies whatever the relay says, and no relay defence touches "
                  "it: every arm that does the task sits well above chance there, "
                  "including the ones the assertion detector calls clean, and the "
                  "arms that do not are simply the arms that failed the task. So a "
                  "defence can take relay disclosure to chance and leave "
                  "answer-implied disclosure exactly where it was. **The second "
                  "floor and utility trade against each other by construction** -- "
                  "an arm cannot score high utility and low answer-implied leakage "
                  "at once, because doing the task *is* that leak."
                  % arm_inf[list(arm_inf)[0]]["chance"], "",
                  "So report this beside delta. A delta near 1.0 on decision tasks "
                  "means the agent kept the use and dropped the disclosure, and that "
                  "is still the finding -- but 'dropped the disclosure' cannot mean "
                  "leakage went to zero, and a reader entitled to think it did would "
                  "be misled. The relay-level measurements elsewhere in this report "
                  "are leakage *through the relay text*; this is leakage through the "
                  "task output, which no relay defence can touch.", "",
                  "It is a property of the construction, not of the models: the "
                  "scenarios were built so that S determines the answer, and that is "
                  "what makes delta measurable at all. A testbed where S only "
                  "*shifts* the answer distribution would have a lower floor and a "
                  "weaker delta; the trade is stated here rather than hidden.", ""]

        pw = A.power_note(p)
        if pw:
            L += ["### Power, stated honestly", "",
                  "- n = %d scenarios; sd of the paired difference = %.3f"
                  % (pw["n_scenarios"], pw["sd_paired_diff"]),
                  "- smallest delta gap detectable at 80%% power: **%.3f**"
                  % pw["mde_delta_80pct"],
                  "", "The plan asserts v1 can only detect a delta gap of about "
                  "0.25 or more. That number is this one, and it depends on a "
                  "variance that only a real run can supply -- so it is computed "
                  "here rather than quoted.", ""]

        # --- pre-registered robustness check ------------------------------
        from petal import prereg as _pre
        edited = set(_pre.edited_scenarios())
        touched = [sid for sid in p.scenarios if sid in edited]
        if touched:
            q = A.subset(p, edited)
            L += ["### Robustness: excluding the edited scenarios", "",
                  "Five restricted-category texts were reworded between the audit "
                  "pilot and the freeze, each fixing a contradiction statable from "
                  "the scenario text alone (every diff is in "
                  "`results/prefreeze_rule.md`). The edits were to *categories*, so "
                  "they touch **%d of this panel's %d scenarios** -- not only the "
                  "ones that failed the audit, which would have been the narrower "
                  "and more flattering set to exclude. This check was pre-registered "
                  "before the freeze."
                  % (len(touched), len(p.scenarios)), "",
                  "| quantity | all %d | excluding %d edited (n=%d) |"
                  % (len(p.scenarios), len(touched), len(q.scenarios)),
                  "|---|---|---|"]
            dq = A.delta_normalised_table(q, ["petal_text", "constraint_only",
                                              "decision_only"],
                                          n_boot=cfg.n_bootstrap, seed=cfg.seed)
            for arm in ("petal_text", "constraint_only", "decision_only"):
                if arm in dn and arm in dq:
                    L.append("| delta/ceiling, `%s` | %s | %s |"
                             % (arm, dn[arm], dq[arm]))
            for nm, fn in (("Lambda", A.lambda_causal), ("Phi_floor", A.phi_floor)):
                a1, a2 = fn(p), fn(q)
                L.append("| %s | %s | %s |"
                         % (nm, "n/a" if a1 != a1 else "%.3f" % a1,
                            "n/a" if a2 != a2 else "%.3f" % a2))
            L.append("")
            out_json.setdefault("robustness", {})[ut] = {
                "n_all": len(p.scenarios), "n_excluded": len(touched),
                "edited_scenarios": sorted(touched),
                "delta_over_ceiling": {a: iv.to_dict() for a, iv in dq.items()},
                "lambda": A.lambda_causal(q), "phi_floor": A.phi_floor(q)}

        out_json["use_types"][ut] = {
            "n_scenarios": len(p.scenarios),
            "utility": {a: A._mean(p.utility[a]) for a in p.arms()},
            "leak": {a: {ch: A.leak_rate(p, a, ch) for ch in A.CHANNELS}
                     for a in p.arms()},
            "lambda": lam, "phi_floor": flo,
            "delta": {a: iv.to_dict() for a, iv in dt.items()},
            "delta_over_ceiling": {a: iv.to_dict() for a, iv in dn.items()},
            "ceiling_delta_scale": cl.to_dict() if cl is not None else None,
            "u_max_no_s_mean": design_ceiling,
            "decision_rule": {str(k): A.decision_rule(p, kappa=k,
                                                      lam=cfg.lambda_length)
                              for k in [cfg.kappa] + list(cfg.kappa_sensitivity)},
            "tests": t["holm"], "power": pw,
            **({"arm_inferential": arm_inf} if ut == "decision" else {}),
        }

    out = Path(args.out) if args.out else paths.RESULTS / "exp1.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    (paths.RESULTS / "exp1.json").write_text(json.dumps(out_json, indent=1,
                                                        default=float),
                                             encoding="utf-8")
    print("\n".join(L))
    print("\n-> %s\n-> %s" % (out, paths.RESULTS / "exp1.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
