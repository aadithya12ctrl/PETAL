"""Experiment configuration.

Everything that must be identical between the dry run and the reported run lives
here, is written to config.json, and is hashed into every cache key.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any

from .paths import CONFIG


@dataclass
class ModelSpec:
    """One pinned model role.

    `provider_order` + allow_fallbacks=False is what makes a run reproducible on
    OpenRouter: without it the same model id can be served by providers with
    different quantisation, different tokenisers and different seed semantics.
    """
    role: str
    model: str
    provider_order: list[str] = field(default_factory=list)
    allow_fallbacks: bool = False
    require_parameters: bool = True
    temperature: float = 0.7
    max_tokens: int = 400
    fallback_model: str | None = None   # used only if `model` is unavailable; logged loudly
    #: OpenRouter reasoning effort, for models that think before answering.
    #: Reasoning tokens bill as *output*, so a reasoning model left on its
    #: default can cost several times what the completion length suggests.
    #: "low" on the cheap audit role keeps the pilot in cents; "" omits the
    #: field entirely for models that do not take it.
    reasoning_effort: str = ""
    #: Tri-state. False sends {"enabled": false} and turns thinking OFF, which
    #: is what PETAL_execution_plan.md section 2 specifies for the primary
    #: agent family ("thinking off"). The client never sent it, so the model
    #: thought by default and spent its whole max_tokens budget on reasoning
    #: tokens: 14 of the first 19 real calls returned no content at all. None
    #: omits the field entirely.
    reasoning_enabled: bool | None = None
    #: Recorded, not sent. The served weights' precision, so the paper can say
    #: which numbers it is reporting. OpenRouter routed us to an fp4 host by
    #: default; pinning is what makes this knowable at all.
    quantization: str = ""

    def routing(self) -> dict[str, Any]:
        p: dict[str, Any] = {
            "allow_fallbacks": self.allow_fallbacks,
            "require_parameters": self.require_parameters,
        }
        if self.provider_order:
            p["order"] = list(self.provider_order)
        return p


@dataclass
class Config:
    # --- spend control -------------------------------------------------
    spend_limit_usd: float = 9.00          # hard stop (plan §5 "hard rules")
    warn_at_usd: float = 6.00
    # --- determinism --------------------------------------------------
    seed: int = 20261109
    second_seed: int = 777                 # Exp 1 replication seed
    # --- models (plan §2) ---------------------------------------------
    models: dict[str, ModelSpec] = field(default_factory=dict)
    # --- testbed ------------------------------------------------------
    n_scenarios: int = 60
    n_decision: int = 30
    n_content: int = 30
    domains: list[str] = field(default_factory=lambda: [
        "clinic_scheduling", "insurance_claims", "hr_leave",
        "legal_intake", "loan_prescreen", "travel_accessibility",
    ])
    hops: int = 3                          # planner -> worker -> reporter
    ladder_hops: int = 5                   # Exp 2
    shared_memory: bool = False            # v1: off by design, so T1 side term == 0
    # --- decision rule (§4.2.4) ---------------------------------------
    kappa: float = 2.0
    kappa_sensitivity: list[float] = field(default_factory=lambda: [1.0, 5.0])
    lambda_length: float = 0.02
    # --- gap detection (Definition 2) ---------------------------------
    tau_gap: float = 0.15
    gap_samples: int = 0                   # 0 = use the cheap logit/lexical proxy, not resampling
    # --- detector (§4 / E0) -------------------------------------------
    # The plan names DeBERTa-MNLI. On this machine DeBERTa-v3 segfaults in the
    # native tokenizer and bart-large-mnli exceeds the pagefile, so the fast
    # detector is a distilled MNLI cross-encoder, which measured cleanly on the
    # testbed probes (see README phase 4). Overridable.
    nli_model: str = "typeform/distilbert-base-uncased-mnli"
    nli_entail_hi: float = 0.75            # >= hi  -> leak, no judge call
    nli_entail_lo: float = 0.25            # <= lo  -> clean, no judge call
    judge_temperature: float = 0.0
    # --- analysis ------------------------------------------------------
    n_bootstrap: int = 10000
    alpha: float = 0.05

    def to_json(self) -> str:
        d = asdict(self)
        d["models"] = {k: asdict(v) for k, v in self.models.items()}
        return json.dumps(d, indent=2, sort_keys=True)

    def save(self, path=CONFIG) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path=CONFIG) -> "Config":
        d = json.loads(path.read_text(encoding="utf-8"))
        models = {k: ModelSpec(**v) for k, v in d.pop("models", {}).items()}
        cfg = cls(**d)
        cfg.models = models
        return cfg

    # --- model-role accessors ----------------------------------------
    def model(self, role: str) -> ModelSpec:
        try:
            return self.models[role]
        except KeyError as e:
            raise KeyError(f"no model configured for role {role!r}; "
                           f"have {sorted(self.models)}") from e


def default_config() -> Config:
    """The configuration the plan asks for.

    Model ids are taken verbatim from PETAL_execution_plan.md §2 and are verified
    against the live OpenRouter catalogue by scripts/check_models.py, which
    rewrites config.json with the resolved ids before any paid run.
    """
    cfg = Config()
    cfg.models = {
        "agent_a": ModelSpec(
            role="agent_a", model="qwen/qwen3.8-27b",
            # Measured with thinking off: planner completions run 368-674
            # tokens (median 445). At 400 seven of ten planner calls were cut
            # off mid-message; a truncated relay is scored as a bad answer and
            # says nothing about the model.
            temperature=0.7, max_tokens=900,
            # "thinking off", per plan section 2. Without it the model reasons
            # and never reaches a visible answer.
            reasoning_enabled=False,
            # Pinned from the model's endpoints list: honours seed, accepts the
            # reasoning toggle, and serves bf16 -- the highest precision on
            # offer. Unpinned, OpenRouter routed to an fp4 host.
            provider_order=["DeepInfra"], quantization="bf16",
            fallback_model="qwen/qwen3-30b-a3b-instruct-2507",
        ),
        "agent_b": ModelSpec(
            role="agent_b", model="meta-llama/llama-3.3-70b-instruct",
            temperature=0.7, max_tokens=400,
            # not a reasoning model; pinned for the same reproducibility reason
            provider_order=["CoreWeave"], quantization="fp16",
        ),
        "judge": ModelSpec(
            role="judge", model="deepseek/deepseek-v4-pro",
            temperature=0.0, max_tokens=200,
            fallback_model="deepseek/deepseek-chat-v3.1",
        ),
        "dev": ModelSpec(
            role="dev", model="openai/gpt-oss-20b",
            # Also a reasoning model, so effort is pinned low: reasoning tokens
            # bill as output and the cheap audit role would not be cheap.
            # max_tokens 900 for the same reason as agent_a -- the first pilot
            # ran at 400 and truncated 10.3% of its responses, five times the
            # guard's threshold, which would have made the audit's Full-arm
            # accuracy a measurement of the token cap.
            temperature=0.7, max_tokens=900,
            reasoning_effort="low",
            provider_order=["DeepInfra"], quantization="bf16",
        ),
    }
    return cfg


def api_key() -> str | None:
    """OpenRouter key from the environment or a local .env (never committed)."""
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k.strip()
    from .paths import ROOT
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None
