"""LLM client: OpenRouter (paid) and Mock (free, deterministic) behind one interface.

Design rules this file enforces, all from PETAL_execution_plan.md section 2 / 5:
  * provider pinned, allow_fallbacks=False, require_parameters=True
  * fixed seed, temperature per role
  * the returned `model` and `provider` are logged with every call
  * every call is disk-cached by request hash
  * every uncached paid call is reserved against a hard spend ceiling first
  * MockBackend lets the entire pipeline run end-to-end at zero cost
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .cache import DiskCache, request_key
from .config import Config, ModelSpec, api_key
from .costmeter import CostMeter, Price

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


# --------------------------------------------------------------------- tokens
def count_tokens(text: str) -> int:
    """Approximate token count, used only for the pre-call cost *upper bound*."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def count_messages(messages: list[dict[str, str]]) -> int:
    return sum(count_tokens(m.get("content", "")) + 4 for m in messages)


# ------------------------------------------------------------------ response
@dataclass
class LLMResponse:
    text: str
    role: str
    model: str                     # the id we asked for
    model_served: str | None       # what OpenRouter says it served
    provider: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cached: bool
    latency_s: float
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class Backend:
    name = "base"
    #: Participates in the cache key. Empty for a real provider, whose responses
    #: do not depend on our code; non-empty for anything we simulate, so that
    #: changing the simulation invalidates its cached outputs instead of letting
    #: stale ones outlive the logic that produced them.
    version = ""

    def complete(self, spec: ModelSpec, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


# ----------------------------------------------------------------- openrouter
class OpenRouterBackend(Backend):
    name = "openrouter"

    def __init__(self, key: str, timeout: float = 120.0, max_retries: int = 4,
                 app_title: str = "PETAL-research",
                 max_rate_limit_retries: int = 8,
                 max_network_retries: int = 8):
        self.key = key
        self.timeout = timeout
        self.max_retries = max_retries
        #: 429s are counted separately and waited out far more patiently than
        #: other transient errors: they come from the pinned provider's shared
        #: pool, and clear in minutes rather than seconds.
        self.max_rate_limit_retries = max_rate_limit_retries
        #: Connection and DNS failures are counted and waited out the same way,
        #: and for the same reason: they are local, transient, and outlast a
        #: short backoff. See the comment in `complete`.
        self.max_network_retries = max_network_retries
        self.app_title = app_title
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        # No personal identifiers are sent; X-Title is a generic client name.
        return {
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "X-Title": self.app_title,
        }

    def complete(self, spec: ModelSpec, payload: dict[str, Any]) -> dict[str, Any]:
        last_err: Exception | None = None
        rate_tries = 0
        net_tries = 0
        attempt = -1
        while True:
            attempt += 1
            if attempt >= self.max_retries + rate_tries + net_tries:
                break
            try:
                r = self._session.post(OPENROUTER_URL, headers=self._headers(),
                                       data=json.dumps(payload), timeout=self.timeout)
            except requests.RequestException as e:
                # A dropped connection or a failed DNS lookup is the same kind
                # of event as the upstream 429 handled below: local, transient,
                # and lasting longer than the ~15s that four attempts of
                # min(2**n, 20) give up after. Stage 1 of the reported run died
                # at scenario 24 of 60 on `Failed to resolve 'openrouter.ai'`;
                # the network was back within the minute, but the run was gone.
                # Every completed call is in the disk cache, so the only cost of
                # waiting is wall-clock, and the only cost of *not* waiting is
                # the whole run.
                last_err = e
                net_tries += 1
                if net_tries > self.max_network_retries:
                    break
                wait = min(15.0 * net_tries, 120.0)
                wait += random.uniform(0, 0.3 * wait)   # de-synchronise
                print("[client] network error (%s); waiting %.0fs (attempt %d/%d)"
                      % (type(e).__name__, wait, net_tries,
                         self.max_network_retries))
                time.sleep(wait)
                continue
            if r.status_code == 200:
                obj = r.json()
                if obj.get("error"):
                    raise RuntimeError("OpenRouter error: " + repr(obj["error"]))
                return obj
            if r.status_code in (408, 429, 500, 502, 503, 504):
                last_err = RuntimeError("HTTP %d: %s" % (r.status_code, r.text[:400]))
                # A 429 here is not our quota. It is the provider's shared pool
                # being exhausted upstream, which lasts minutes, not the ~15s
                # an exponential backoff from 1s gives up after -- the first
                # full pilot died at scenario 51 of 60 that way. Pinning one
                # provider for reproducibility is what exposes us to it, and
                # the alternative (fall back to another host) would silently
                # mix quantisations mid-run. So wait properly instead.
                if r.status_code == 429:
                    rate_tries += 1
                    if rate_tries > self.max_rate_limit_retries:
                        break
                    hdr = r.headers.get("Retry-After")
                    try:
                        wait = float(hdr) if hdr else 0.0
                    except ValueError:
                        wait = 0.0
                    wait = wait or min(20.0 * rate_tries, 180.0)
                    wait += random.uniform(0, 0.3 * wait)   # de-synchronise
                    print("[client] rate-limited upstream; waiting %.0fs "
                          "(attempt %d/%d)"
                          % (wait, rate_tries, self.max_rate_limit_retries))
                    time.sleep(wait)
                    continue
                time.sleep(min(2 ** attempt, 20))
                continue
            raise RuntimeError("OpenRouter HTTP %d: %s" % (r.status_code, r.text[:800]))
        raise RuntimeError("OpenRouter failed after %d attempts (%d rate-limited, "
                           "%d network): %s"
                           % (attempt + 1, rate_tries, net_tries, last_err))


# ----------------------------------------------------------------------- mock
class MockBackend(Backend):
    """Deterministic offline stand-in.

    It is *not* a model simulator. It exists so the harness, the arm logic, the
    detector plumbing and the analysis can be exercised and unit-tested without
    spending anything. Behaviour is driven by a pluggable responder so tests can
    script specific outputs, including deliberate leaks.
    """
    name = "mock"

    def __init__(self, responder: Callable[[ModelSpec, dict[str, Any]], str] | None = None):
        self.responder = responder or self._default_responder
        self.calls: list[dict[str, Any]] = []
        self.version = str(getattr(self.responder, "version", "default"))

    @staticmethod
    def _default_responder(spec: ModelSpec, payload: dict[str, Any]) -> str:
        msgs = payload.get("messages", [])
        h = hashlib.sha256(json.dumps(msgs, sort_keys=True).encode()).hexdigest()
        rng = random.Random(h)
        last = msgs[-1].get("content", "") if msgs else ""
        words = [w for w in last.split() if w.isalpha() and len(w) > 4]
        rng.shuffle(words)
        return "MOCK[" + spec.model + "] " + " ".join(words[:25] or ["mock", "output"])

    def complete(self, spec: ModelSpec, payload: dict[str, Any]) -> dict[str, Any]:
        text = self.responder(spec, payload)
        self.calls.append(payload)
        pt = count_messages(payload.get("messages", []))
        ct = count_tokens(text)
        return {
            "id": "mock-" + hashlib.sha256(text.encode()).hexdigest()[:12],
            "model": spec.model,
            "provider": "mock",
            "choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct,
                      "total_tokens": pt + ct, "cost": 0.0},
        }


# --------------------------------------------------------------------- client
class LLMClient:
    def __init__(self, cfg: Config, backend: Backend | None = None,
                 cache: DiskCache | None = None, meter: CostMeter | None = None,
                 prices: dict[str, Price] | None = None, cache_enabled: bool = True,
                 offline: bool = False, escalation_ceiling: int = 8000):
        self.cfg = cfg
        #: Responses that arrived with no usable text. Counted rather than
        #: raised on, because one truncated completion is a fact about a hard
        #: prompt while a high *rate* is a broken configuration -- and the
        #: difference is only visible in aggregate. `empty_report()` is what
        #: the runners check before they let a run stand.
        self.empty: list[dict[str, Any]] = []
        #: Responses cut off at max_tokens. Tracked separately from `empty`
        #: because the cause and the fix differ, but checked the same way.
        self.truncated: list[dict[str, Any]] = []
        #: Calls that were cut off and retried at a larger budget. Not faults:
        #: the retry is what keeps the truncation out of the data. Counted so
        #: the paper can report how often the escalation fired.
        self.escalated: list[dict[str, Any]] = []
        #: The largest budget a single call may escalate to.
        self.escalation_ceiling = escalation_ceiling
        self.cache = cache if cache is not None else DiskCache(enabled=cache_enabled)
        self.meter = meter or CostMeter(cfg.spend_limit_usd, warn_at_usd=cfg.warn_at_usd,
                                        prices=prices or {})
        self.offline = offline
        if backend is not None:
            self.backend = backend
        else:
            key = api_key()
            self.backend = OpenRouterBackend(key) if (key and not offline) else MockBackend()

    @property
    def is_paid(self) -> bool:
        return isinstance(self.backend, OpenRouterBackend)

    # ------------------------------------------------------------------ call
    def _chat_once(self, role: str, messages: list[dict[str, str]], *,
             seed: int | None = None, temperature: float | None = None,
             max_tokens: int | None = None, tag: str = "",
             model_override: str | None = None,
             response_format: dict[str, Any] | None = None) -> LLMResponse:
        spec = self.cfg.model(role)
        if model_override:
            d = dict(spec.__dict__)
            d["model"] = model_override
            spec = ModelSpec(**d)
        seed = self.cfg.seed if seed is None else seed
        temperature = spec.temperature if temperature is None else temperature
        max_tokens = spec.max_tokens if max_tokens is None else max_tokens

        payload: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "seed": seed,
            "provider": spec.routing(),
            "usage": {"include": True},
        }
        if response_format:
            payload["response_format"] = response_format
        # Reasoning tokens bill as output. A reasoning model on its default
        # effort can cost several times what max_tokens implies, so the effort
        # is pinned per role and participates in the cache key below -- two
        # runs at different efforts are different runs.
        enabled = getattr(spec, "reasoning_enabled", None)
        if enabled is False:
            payload["reasoning"] = {"enabled": False}
        elif getattr(spec, "reasoning_effort", ""):
            payload["reasoning"] = {"effort": spec.reasoning_effort}

        key = request_key(payload, {"role": role, "backend": self.backend.name,
                                    "backend_version": self.backend.version})
        hit = self.cache.get(key)
        if hit is not None:
            return self._from_raw(hit, role, spec, cached=True, latency=0.0, tag=tag)

        if self.is_paid:
            self.meter.reserve(spec.model, count_messages(messages), max_tokens)

        t0 = time.time()
        raw = self.backend.complete(spec, payload)
        latency = time.time() - t0
        self.cache.put(key, raw)
        return self._from_raw(raw, role, spec, cached=False, latency=latency, tag=tag)

    def chat(self, role: str, messages: list[dict[str, str]], **kw) -> LLMResponse:
        """One call, retried at a larger budget if the model was cut off.

        Raising `max_tokens` globally does not fix truncation here, it only
        moves it. Measured on the reported model: at 900 tokens 5.1% of calls
        were cut off, at 2000 still 2.8%, while the median completion is 335
        tokens and p95 is 1118 -- a thin, heavy tail rather than a budget that
        is uniformly too small. Each doubling costs a full re-run of the
        matrix and removes about half of what is left.

        Truncation is also not harmless noise. A run touched by a truncated
        call still produces a parseable FINAL line 93% of the time, so the
        harness-failure exclusion does not catch it, and it scores 0.179 mean
        utility on decision tasks against 0.670 for clean runs. It is
        concentrated in the arms whose planner lacks the restricted fact,
        because those deliberate instead of answering, so it depresses U_drop
        hardest and biases every delta upward.

        So escalate per call instead: double the budget for the call that was
        cut off, up to the ceiling, and leave every other call alone. The
        decision is taken on `finish_reason` alone, never on the content or
        the score, so it is a rule rather than a judgement. The first attempt
        keeps its cache key, which is why this costs a few cents rather than
        another full pass.
        """
        budget = kw.pop("max_tokens", None)
        if budget is None:
            budget = self.cfg.model(role).max_tokens
        while True:
            resp = self._chat_once(role, messages, max_tokens=budget, **kw)
            if resp.finish_reason != "length":
                break
            nxt = min(budget * 2, self.escalation_ceiling)
            if nxt <= budget:
                break                      # at the ceiling; report as truncated
            self.escalated.append({
                "role": role, "model": resp.model, "from": budget, "to": nxt,
                "completion_tokens": resp.completion_tokens,
                "tag": kw.get("tag", ""),
            })
            budget = nxt
        self._note_outcome(resp)
        return resp

    def _note_outcome(self, resp: LLMResponse) -> None:
        """Record the outcome of the call actually returned.

        Only the final attempt counts. An intermediate attempt that was cut
        off and then retried at a larger budget is an escalation, not a
        truncated result, and counting it would make the guard refuse a run
        whose data is sound.
        """
        usage = (resp.raw.get("usage") or {})
        if resp.finish_reason == "length":
            self.truncated.append({
                "role": resp.role, "model": resp.model, "provider": resp.provider,
                "completion_tokens": resp.completion_tokens,
                "max_tokens": self.escalation_ceiling,
                "chars": len(resp.text), "cached": resp.cached, "tag": "",
            })
        if not resp.text:
            rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            self.empty.append({
                "role": resp.role, "model": resp.model, "provider": resp.provider,
                "finish_reason": resp.finish_reason,
                "completion_tokens": resp.completion_tokens,
                "reasoning_tokens": rt, "max_tokens": self.escalation_ceiling,
                "cached": resp.cached, "tag": "",
            })

    # ----------------------------------------------------------------- parse
    def _from_raw(self, raw: dict[str, Any], role: str, spec: ModelSpec, *,
                  cached: bool, latency: float, tag: str) -> LLMResponse:
        choices = raw.get("choices") or [{}]
        msg = choices[0].get("message") or {}
        text = (msg.get("content") or "").strip()
        usage = raw.get("usage") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        reported = usage.get("cost")
        if cached:
            cost_in = 0.0
        elif reported is not None:
            cost_in = float(reported)
        else:
            cost_in = None
        cost = self.meter.commit(
            model=spec.model, provider=raw.get("provider"), role=role,
            prompt_tokens=pt, completion_tokens=ct, cost_usd=cost_in,
            cached=cached, tag=tag,
        )
        finish = choices[0].get("finish_reason")
        # A message cut off mid-sentence is scored as a bad answer exactly as
        # an empty one is, and is just as silent -- it still returns plenty of
        # text. An empty completion is the same silence from a reasoning model
        # that spent its whole budget thinking. Both are recorded, but by
        # `_note_outcome` on the call that is actually returned: `chat` retries
        # a truncated call at a larger budget first, and an attempt that was
        # superseded is an escalation rather than a result.
        return LLMResponse(
            text=text, role=role, model=spec.model,
            model_served=raw.get("model"), provider=raw.get("provider"),
            prompt_tokens=pt, completion_tokens=ct, cost_usd=cost,
            cached=cached, latency_s=latency,
            finish_reason=finish, raw=raw,
        )

    def empty_report(self, n_calls: int) -> dict[str, Any]:
        """Summary of empty completions, for a runner to act on."""
        from collections import Counter
        by = Counter((e["model"], e.get("provider"), e.get("finish_reason"))
                     for e in self.empty)
        starved = sum(1 for e in self.empty
                      if e.get("finish_reason") == "length"
                      and e.get("reasoning_tokens")
                      and e["reasoning_tokens"] >= e.get("max_tokens", 0))
        tby = Counter((e["model"], e.get("provider")) for e in self.truncated)
        eby = Counter((e["model"], "%d->%d" % (e["from"], e["to"]))
                      for e in self.escalated)
        return {"n_escalated": len(self.escalated),
                "escalated_by": {"%s | %s" % k: v for k, v in eby.items()},
                "n_empty": len(self.empty), "n_calls": n_calls,
                "rate": (len(self.empty) / n_calls) if n_calls else 0.0,
                "budget_starved": starved,
                "by": {"%s | %s | %s" % k: v for k, v in by.items()},
                "n_truncated": len(self.truncated),
                "truncated_rate": (len(self.truncated) / n_calls) if n_calls else 0.0,
                "truncated_by": {"%s | %s" % k: v for k, v in tby.items()}}


# ------------------------------------------------------------------ catalogue
def fetch_catalogue(timeout: float = 60.0) -> dict[str, Any]:
    """Public OpenRouter model list. No key needed, no cost."""
    r = requests.get(OPENROUTER_MODELS_URL, timeout=timeout,
                     headers={"X-Title": "PETAL-research"})
    r.raise_for_status()
    return r.json()


def prices_from_catalogue(cat: dict[str, Any]) -> dict[str, Price]:
    out: dict[str, Price] = {}
    for m in cat.get("data", []):
        p = m.get("pricing") or {}
        try:
            out[m["id"]] = Price(prompt=float(p.get("prompt", 0) or 0),
                                 completion=float(p.get("completion", 0) or 0))
        except (TypeError, ValueError, KeyError):
            continue
    return out
