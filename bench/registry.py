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


# Display-name aliases. Maps the noisy storage names (Ollama tags, HF URLs,
# lmstudio: prefixes) to clean human-readable labels for reports, leaderboards,
# and tournament output. The DB stores raw names; this is purely cosmetic so
# historical data isn't disrupted. Unknown models fall through to their raw name.
DISPLAY_NAMES: dict[str, str] = {
    # Ollama-packaged
    "gemma4:e4b": "gemma4-e4b",
    "gemma4:26b": "gemma4-26b",
    "gemma3n:latest": "gemma3n",
    "gpt-oss:20b": "gpt-oss-20b",
    "phi4:14b": "phi4-14b",
    "phi4-mini:3.8b": "phi4-mini-3.8b",
    "phi4-reasoning:latest": "phi4-reasoning",
    "hermes3:8b": "hermes3-8b",
    "llama3.2:latest": "llama3.2-3b",
    "smollm2:1.7b": "smollm2-1.7b",
    "deepseek-r1:1.5b": "deepseek-r1-1.5b",
    "qwen2.5:1.5b-instruct": "qwen2.5-1.5b",
    "qwen2.5-coder:3b": "qwen2.5-coder-3b",
    "qwen2.5-coder:1.5b-base": "qwen2.5-coder-1.5b-base",
    "qwen3-coder:30b": "qwen3-coder-30b",
    "devstral-small-2:latest": "devstral-small-2",
    "mistral-nemo:12b-instruct-2407-q4_K_M": "mistral-nemo-12b",
    # HuggingFace GGUF tags
    "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:Q4_K_M": "hermes4-14b",
    "hf.co/unsloth/SmolLM3-3B-GGUF:Q4_K_M": "smollm3-3b",
    "hf.co/unsloth/granite-4.0-h-tiny-GGUF:Q4_K_M": "granite4-h-tiny",
    "hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_XL": "gemma4-26b-unsloth",
    # LM Studio (OpenAI-compatible backend)
    "lmstudio:gemma-4-e4b-it": "gemma4-e4b-q4ks-fast",
}


def display_name(model: str) -> str:
    """Return clean display label for a stored model name. Falls through if unknown."""
    return DISPLAY_NAMES.get(model, model)


# Explicit exclusions: vision / embedding models (different eval shape)
EXCLUDE = {"nomic-embed-text", "deepseek-ocr"}


def should_include(name: str) -> bool:
    base = name.split(":")[0]
    return base not in EXCLUDE
