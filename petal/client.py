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
                 app_title: str = "PETAL-research"):
        self.key = key
        self.timeout = timeout
        self.max_retries = max_retries
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
        for attempt in range(self.max_retries):
            try:
                r = self._session.post(OPENROUTER_URL, headers=self._headers(),
                                       data=json.dumps(payload), timeout=self.timeout)
            except requests.RequestException as e:
                last_err = e
                time.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code == 200:
                obj = r.json()
                if obj.get("error"):
                    raise RuntimeError("OpenRouter error: " + repr(obj["error"]))
                return obj
            if r.status_code in (408, 429, 500, 502, 503, 504):
                last_err = RuntimeError("HTTP %d: %s" % (r.status_code, r.text[:400]))
                time.sleep(min(2 ** attempt, 20))
                continue
            raise RuntimeError("OpenRouter HTTP %d: %s" % (r.status_code, r.text[:800]))
        raise RuntimeError("OpenRouter failed after %d attempts: %s"
                           % (self.max_retries, last_err))


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
                 offline: bool = False):
        self.cfg = cfg
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
    def chat(self, role: str, messages: list[dict[str, str]], *,
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
        return LLMResponse(
            text=text, role=role, model=spec.model,
            model_served=raw.get("model"), provider=raw.get("provider"),
            prompt_tokens=pt, completion_tokens=ct, cost_usd=cost,
            cached=cached, latency_s=latency,
            finish_reason=choices[0].get("finish_reason"), raw=raw,
        )


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
