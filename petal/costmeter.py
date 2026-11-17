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
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import LEDGER


class SpendLimitExceeded(RuntimeError):
    pass


def _append_locked(path: "Path", line: bytes, *, tries: int = 3000) -> None:
    """Append one record to the ledger under an exclusive cross-process lock.

    Two runs sharing a ledger corrupt it, and on Windows they do so silently.
    Running Experiment 2 and the LLM adversary at the same time left
    `{"ts": ..., "completion_tokens": 2` on one line and `"}` on the next, and
    a thread test then showed 294 of 320 records simply missing -- no
    exception, no torn line, just gone.

    The cause is that `O_APPEND` is emulated on Windows as seek-to-end then
    write, which is not atomic: two writers resolve the same end offset and
    one overwrites the other. POSIX `O_APPEND` would be safe; relying on it
    is not portable, and this project runs on Windows.

    Why it matters more than a lost cent: `_load` skips unparseable lines, so a
    damaged ledger makes the recomputed total *lower* than the true spend, and
    the hard ceiling is computed from that total. The failure direction is
    toward overspending.

    So: a sidecar lock file, an exclusive byte-range lock on it, then the
    append. The lock is advisory between cooperating writers, which is exactly
    what this is -- every writer goes through here.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    lfd = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        _flock(lfd, tries)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.lseek(fd, 0, os.SEEK_END)
                os.write(fd, line)
            finally:
                os.close(fd)
        finally:
            _funlock(lfd)
    finally:
        os.close(lfd)


def _flock(fd: int, tries: int) -> None:
    try:
        import fcntl
    except ImportError:
        import msvcrt
        for _ in range(tries):
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)
        # 30s of contention, not 2s. The budget was 200 tries, and a full test
        # suite running beside a paid run exhausted it -- on a machine at its
        # commit limit, eight writers can block each other for longer than two
        # seconds. Raising here is the safe direction (refuse rather than lose
        # a record), but it aborts a paid run that may be an hour in, so the
        # budget should be far larger than any plausible contention.
        raise RuntimeError("could not lock the spend ledger after %.0fs; "
                           "refusing to append a record that might be lost"
                           % (tries * 0.01))
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _funlock(fd: int) -> None:
    try:
        import fcntl
    except ImportError:
        import msvcrt
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


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
        _append_locked(self.ledger,
                       (json.dumps(rec, ensure_ascii=False) + "\n")
                       .encode("utf-8"))
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
