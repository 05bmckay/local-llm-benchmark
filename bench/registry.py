"""Model registry: size buckets + metadata.

Size buckets are fairness groups. A 1.5B model should never be compared
head-to-head with a 30B model on an absolute leaderboard — only within its
bucket and on the overall throughput-weighted composite.
"""
from __future__ import annotations

from dataclasses import dataclass

# Ordered; first match wins
BUCKETS: list[tuple[str, float]] = [
    ("<1B", 1.0),
    ("<3B", 3.0),
    ("<7B", 7.0),
    ("<10B", 10.0),
    ("<15B", 15.0),
    ("<25B", 25.0),
    ("<35B", 35.0),
    (">=35B", float("inf")),
]


def bucket_for(params_b: float) -> str:
    for name, cap in BUCKETS:
        if params_b < cap:
            return name
    return ">=35B"


@dataclass
class ModelInfo:
    name: str              # ollama tag, e.g. "qwen3-coder:30b"
    params_b: float        # billions
    bucket: str
    family: str
    quant: str

    @property
    def approx_ram_gb(self) -> float:
        # rough Q4 working-set estimate
        return self.params_b * 0.65 + 1.0


# Explicit exclusions: vision / embedding models (different eval shape)
EXCLUDE = {"nomic-embed-text", "deepseek-ocr"}


def should_include(name: str) -> bool:
    base = name.split(":")[0]
    return base not in EXCLUDE
