"""The silence guard, in one place because having it in only one place failed.

`run_exp1.py` has refused to report a run whose calls came back empty since
the first pilot. `llm_adversary.py` never had that check, and on 2026-11-14 it
printed a clean-looking recovery table in which **81 of 120 relays had no
answer in them at all** -- the attacker's reply had been truncated at the
judge role's 200-token budget and the empty string was scored as a failure to
identify S.

The rate was not uniform: Full 40% silent, Constraint-only 63%, Decision-only
80%, Drop 87%. The thinner the relay, the longer the model deliberated, the
more often it hit the cap. So the silence suppressed measured recovery most in
precisely the arms the hypothesis predicts to be lowest, which is to say the
bug flattered the result.

Two fixes follow from that, and this module is the second:

1.  `client._cut_off_at` no longer trusts `finish_reason` alone, because the
    provider reported something other than "length" on 79 of those 81.
2.  The guard lives here, and every paid runner calls it. A guard that one
    script has and another does not is not a guard, it is a habit.
"""
from __future__ import annotations

from typing import Any


class RunRejected(SystemExit):
    """Raised instead of reporting a run whose data cannot carry the claim."""


def report_and_guard(client: Any, n_calls: int, *,
                     empty_max: float = 0.02,
                     truncated_max: float = 0.02,
                     printer: Any = print) -> dict[str, Any]:
    """Print the escalation/empty/truncation report, then refuse bad runs.

    `empty_max` and `truncated_max` are the fractions of calls allowed to come
    back with no text, or cut off at the budget, before the run is rejected.
    Both default to 2%: below that the affected calls cannot move a rate by a
    percentage point, above it they can.

    Returns the report so a caller can record it beside the results.
    """
    rep = client.empty_report(n_calls)

    if rep.get("n_escalated"):
        # Not a fault: these are the calls that ran past their budget and were
        # retried at a larger one. Reported because the rate belongs in the
        # paper -- it is how often the model wanted more room than configured.
        printer("\nESCALATED after truncation: %d of %d calls (%.1f%%)"
                % (rep["n_escalated"], rep["n_calls"],
                   100 * rep["n_escalated"] / max(1, rep["n_calls"])))
        for k, v in sorted(rep["escalated_by"].items()):
            printer("   %-50s %d" % (k, v))

    if rep["n_empty"]:
        printer("\nEMPTY COMPLETIONS: %d of %d calls (%.1f%%)%s"
                % (rep["n_empty"], rep["n_calls"], 100 * rep["rate"],
                   "; %d exhausted max_tokens on reasoning" % rep["budget_starved"]
                   if rep["budget_starved"] else ""))
        for k, v in sorted(rep["by"].items()):
            printer("   %-60s %d" % (k, v))
        if rep["rate"] > empty_max:
            raise RunRejected(
                "\nrefusing to report this run: %.1f%% of calls returned no text.\n"
                "A completion with no content scores as a wrong answer, so these "
                "would be indistinguishable from genuine failures.\n"
                "If finish_reason is 'length' with reasoning_tokens at max_tokens, "
                "the model is a reasoning model whose budget is too small: raise "
                "max_tokens, turn thinking off (reasoning_enabled=False), or pin "
                "an instruct variant." % (100 * rep["rate"]))

    if rep["n_truncated"]:
        printer("\nTRUNCATED AT max_tokens: %d of %d calls (%.1f%%)"
                % (rep["n_truncated"], rep["n_calls"],
                   100 * rep["truncated_rate"]))
        for k, v in sorted(rep["truncated_by"].items()):
            printer("   %-50s %d" % (k, v))
        if rep["truncated_rate"] > truncated_max:
            raise RunRejected(
                "\nrefusing to report this run: %.1f%% of calls were cut off at "
                "max_tokens, which is above the %.0f%% the protocol allows.\n"
                "A reply truncated mid-sentence is scored as a bad answer, so "
                "the cap would be part of the measurement."
                % (100 * rep["truncated_rate"], 100 * truncated_max))

    return rep
