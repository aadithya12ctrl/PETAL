"""Single source of truth for on-disk locations."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCENARIOS = DATA / "scenarios"
RUNS = ROOT / "runs"
CACHE = RUNS / "cache"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
PAPER = ROOT / "paper"

LEDGER = RUNS / "ledger.jsonl"
SPEND_STATE = RUNS / "spend_state.json"
CONFIG = ROOT / "config.json"
MODEL_CATALOG = DATA / "openrouter_models.json"


def ensure_dirs() -> None:
    for p in (DATA, SCENARIOS, RUNS, CACHE, RESULTS, FIGURES, PAPER):
        p.mkdir(parents=True, exist_ok=True)
