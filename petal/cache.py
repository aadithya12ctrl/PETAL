"""Content-addressed disk cache for LLM calls.

Plan §5 hard rule: "Disk-cache every call by hash of (model, provider, messages,
seed)". We hash the full request body plus the role, so a change to temperature,
max_tokens or routing produces a new key rather than silently reusing a response
generated under different settings.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .paths import CACHE


def request_key(payload: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
    """Stable sha256 over the canonicalised request."""
    blob = {"payload": payload, "extra": extra or {}}
    s = json.dumps(blob, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, root: Path = CACHE, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.misses += 1
            return None
        self.hits += 1
        return obj

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # atomic write: a half-written cache entry would be a silent data error
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            os.replace(tmp, p)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}

    def size(self) -> int:
        return sum(1 for _ in self.root.rglob("*.json"))
