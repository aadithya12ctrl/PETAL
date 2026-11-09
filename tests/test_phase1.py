"""Phase 1 tests: cache keying, spend ceiling, ledger durability, routing pins.

Run: py -3.12 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal.cache import DiskCache, request_key
from petal.client import LLMClient, MockBackend, count_tokens
from petal.config import Config, ModelSpec, default_config
from petal.costmeter import CostMeter, Price, SpendLimitExceeded


def tmp_client(tmp: Path, cfg: Config | None = None, prices=None, limit=9.0):
    cfg = cfg or default_config()
    cfg.spend_limit_usd = limit
    cache = DiskCache(root=tmp / "cache")
    meter = CostMeter(limit, ledger=tmp / "ledger.jsonl", prices=prices or {})
    return LLMClient(cfg, backend=MockBackend(), cache=cache, meter=meter), cfg, meter, cache


MSG = [{"role": "user", "content": "relay the appointment plan for the client please"}]


class TestCacheKey(unittest.TestCase):
    def test_key_is_stable_under_dict_order(self):
        a = {"model": "m", "messages": MSG, "temperature": 0.7, "seed": 1}
        b = {"seed": 1, "temperature": 0.7, "messages": MSG, "model": "m"}
        self.assertEqual(request_key(a), request_key(b))

    def test_key_changes_with_every_pinned_field(self):
        base = {"model": "m", "messages": MSG, "temperature": 0.7, "seed": 1,
                "max_tokens": 400, "provider": {"allow_fallbacks": False}}
        k0 = request_key(base)
        for field, new in [("model", "m2"), ("temperature", 0.0), ("seed", 2),
                           ("max_tokens", 401),
                           ("provider", {"allow_fallbacks": True})]:
            mutated = dict(base)
            mutated[field] = new
            self.assertNotEqual(k0, request_key(mutated), field)
        mutated = dict(base)
        mutated["messages"] = [{"role": "user", "content": "different"}]
        self.assertNotEqual(k0, request_key(mutated), "messages")

    def test_role_namespaces_the_key(self):
        p = {"model": "m", "messages": MSG}
        self.assertNotEqual(request_key(p, {"role": "agent_a"}),
                            request_key(p, {"role": "judge"}))


class TestCache(unittest.TestCase):
    def test_roundtrip_and_hit_counting(self):
        with tempfile.TemporaryDirectory() as d:
            c = DiskCache(root=Path(d))
            self.assertIsNone(c.get("abc123"))
            c.put("abc123", {"x": 1})
            self.assertEqual(c.get("abc123"), {"x": 1})
            self.assertEqual(c.stats(), {"hits": 1, "misses": 1})
            self.assertEqual(c.size(), 1)

    def test_corrupt_entry_is_a_miss_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            c = DiskCache(root=Path(d))
            c.put("ff00", {"x": 1})
            p = c._path("ff00")
            p.write_text("{not json", encoding="utf-8")
            self.assertIsNone(c.get("ff00"))

    def test_second_identical_call_is_served_from_cache(self):
        with tempfile.TemporaryDirectory() as d:
            cl, *_ = tmp_client(Path(d))
            r1 = cl.chat("agent_a", MSG)
            r2 = cl.chat("agent_a", MSG)
            self.assertFalse(r1.cached)
            self.assertTrue(r2.cached)
            self.assertEqual(r1.text, r2.text)
            self.assertEqual(len(cl.backend.calls), 1)


class TestSpendCeiling(unittest.TestCase):
    PRICES = {"expensive/model": Price(prompt=1e-3, completion=1e-3)}

    def test_reserve_refuses_when_upper_bound_crosses_limit(self):
        with tempfile.TemporaryDirectory() as d:
            m = CostMeter(0.50, ledger=Path(d) / "l.jsonl", prices=self.PRICES)
            # 1000 prompt + 1000 max tokens at $1e-3/tok = $2.00 > $0.50
            with self.assertRaises(SpendLimitExceeded):
                m.reserve("expensive/model", 1000, 1000)

    def test_reserve_uses_max_tokens_not_actual(self):
        with tempfile.TemporaryDirectory() as d:
            m = CostMeter(1.00, ledger=Path(d) / "l.jsonl", prices=self.PRICES)
            self.assertAlmostEqual(m.reserve("expensive/model", 100, 200), 0.30)

    def test_ledger_total_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            led = Path(d) / "l.jsonl"
            m1 = CostMeter(9.0, ledger=led)
            m1.commit(model="m", provider="p", role="agent_a", prompt_tokens=10,
                      completion_tokens=5, cost_usd=0.25, cached=False)
            m1.commit(model="m", provider="p", role="agent_a", prompt_tokens=10,
                      completion_tokens=5, cost_usd=0.10, cached=False)
            m2 = CostMeter(9.0, ledger=led)
            self.assertAlmostEqual(m2.total, 0.35)
            self.assertAlmostEqual(m2.remaining, 8.65)

    def test_cached_calls_cost_zero_but_are_logged(self):
        with tempfile.TemporaryDirectory() as d:
            cl, _, meter, _ = tmp_client(Path(d))
            cl.chat("agent_a", MSG)
            cl.chat("agent_a", MSG)
            self.assertAlmostEqual(meter.total, 0.0)
            recs = [json.loads(x) for x in
                    (Path(d) / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if x]
            self.assertEqual(len(recs), 2)
            self.assertEqual([r["cached"] for r in recs], [False, True])

    def test_mock_backend_is_never_reserved_against(self):
        # the mock backend must not be able to raise SpendLimitExceeded
        with tempfile.TemporaryDirectory() as d:
            cl, *_ = tmp_client(Path(d), prices=self.PRICES, limit=0.0)
            cl.cfg.models["agent_a"].model = "expensive/model"
            r = cl.chat("agent_a", MSG)
            self.assertEqual(r.cost_usd, 0.0)


class TestRouting(unittest.TestCase):
    def test_routing_pins_fallbacks_off_and_parameters_on(self):
        s = ModelSpec(role="r", model="m", provider_order=["X"])
        self.assertEqual(s.routing(), {"allow_fallbacks": False,
                                       "require_parameters": True,
                                       "order": ["X"]})

    def test_payload_carries_seed_and_routing(self):
        with tempfile.TemporaryDirectory() as d:
            cl, cfg, *_ = tmp_client(Path(d))
            cl.chat("agent_a", MSG, seed=4242)
            p = cl.backend.calls[0]
            self.assertEqual(p["seed"], 4242)
            self.assertIs(p["provider"]["allow_fallbacks"], False)
            self.assertIs(p["provider"]["require_parameters"], True)
            self.assertEqual(p["usage"], {"include": True})

    def test_judge_role_is_temperature_zero(self):
        cfg = default_config()
        self.assertEqual(cfg.model("judge").temperature, 0.0)
        self.assertEqual(cfg.model("agent_a").temperature, 0.7)

    def test_unknown_role_is_a_clear_error(self):
        with self.assertRaises(KeyError):
            default_config().model("nope")


class TestConfigRoundtrip(unittest.TestCase):
    def test_save_load_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            cfg = default_config()
            cfg.save(p)
            back = Config.load(p)
            self.assertEqual(back.to_json(), cfg.to_json())
            self.assertEqual(back.model("agent_b").model, cfg.model("agent_b").model)


class TestTokens(unittest.TestCase):
    def test_token_count_is_positive_and_monotone(self):
        a = count_tokens("hello")
        b = count_tokens("hello " * 50)
        self.assertGreater(a, 0)
        self.assertGreater(b, a)


if __name__ == "__main__":
    unittest.main()
