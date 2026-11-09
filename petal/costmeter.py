"""Spend ledger with a hard ceiling.

Two independent guards, because the failure mode we care about is spending real
money by accident:

1.  `reserve()` refuses a call whose *worst-case* cost would cross the limit.
    The estimate uses the model's catalogue price and max_tokens, i.e. it is an
    upper bound on that one call.
2.  `commit()` appends the *actual* cost to an append-only JSONL ledger. The
    running total is recomputed from the ledger on construction, so a crashed
    run cannot "forget" what it already spent.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import LEDGER


class SpendLimitExceeded(RuntimeError):
    pass


@dataclass
class Price:
    """USD per *token* (OpenRouter publishes per-token strings)."""
    prompt: float = 0.0
    completion: float = 0.0

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return prompt_tokens * self.prompt + completion_tokens * self.completion


class CostMeter:
    def __init__(self, limit_usd: float, ledger: Path = LEDGER,
                 warn_at_usd: float | None = None, prices: dict[str, Price] | None = None):
        self.limit = float(limit_usd)
        self.warn_at = warn_at_usd
        self.ledger = Path(ledger)
        self.prices: dict[str, Price] = prices or {}
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self._total = self._read_total()
        self._calls = 0
        self._warned = False

    # ---------------------------------------------------------------- ledger
    def _read_total(self) -> float:
        if not self.ledger.exists():
            return 0.0
        total = 0.0
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                total += float(json.loads(line).get("cost_usd", 0.0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return total

    @property
    def total(self) -> float:
        return self._total

    @property
    def remaining(self) -> float:
        return self.limit - self._total

    # ------------------------------------------------------------- estimates
    def price(self, model: str) -> Price:
        return self.prices.get(model, Price())

    def estimate(self, model: str, prompt_tokens: int, max_tokens: int) -> float:
        return self.price(model).cost(prompt_tokens, max_tokens)

    def reserve(self, model: str, prompt_tokens: int, max_tokens: int) -> float:
        """Upper-bound cost check before a paid call. Raises if it would cross the limit."""
        est = self.estimate(model, prompt_tokens, max_tokens)
        if self._total + est > self.limit:
            raise SpendLimitExceeded(
                f"call to {model} would cost up to ${est:.5f}; spent ${self._total:.4f} "
                f"of ${self.limit:.2f} limit (remaining ${self.remaining:.4f})"
            )
        return est

    # --------------------------------------------------------------- commits
    def commit(self, *, model: str, provider: str | None, role: str,
               prompt_tokens: int, completion_tokens: int,
               cost_usd: float | None, cached: bool, tag: str = "",
               extra: dict[str, Any] | None = None) -> float:
        """Record one call. Cached calls are logged with cost 0 and still counted."""
        if cost_usd is None:
            cost_usd = 0.0 if cached else self.price(model).cost(prompt_tokens, completion_tokens)
        rec = {
            "ts": time.time(),
            "role": role,
            "model": model,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": round(float(cost_usd), 8),
            "cached": bool(cached),
            "tag": tag,
        }
        if extra:
            rec["extra"] = extra
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._total += float(cost_usd)
        self._calls += 1
        if self.warn_at and not self._warned and self._total >= self.warn_at:
            self._warned = True
            print(f"[costmeter] WARNING: spent ${self._total:.4f} of ${self.limit:.2f}")
        return float(cost_usd)

    def summary(self) -> dict[str, Any]:
        return {
            "total_usd": round(self._total, 6),
            "limit_usd": self.limit,
            "remaining_usd": round(self.remaining, 6),
            "calls_this_session": self._calls,
        }
