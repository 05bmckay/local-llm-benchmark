"""Ollama HTTP client with streaming + timing instrumentation."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

OLLAMA_URL = "http://localhost:11434"


@dataclass
class GenResult:
    text: str
    ttft_ms: float | None
    duration_ms: float
    tokens_out: int
    tokens_per_sec: float
    error: str | None = None


def list_models() -> list[dict]:
    r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    r.raise_for_status()
    return r.json().get("models", [])


def unload(model: str) -> None:
    """Force Ollama to evict a model (keep_alive=0)."""
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=30,
        )
    except Exception:
        pass


def warmup(model: str) -> None:
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": "hi", "stream": False, "keep_alive": "10m"},
            timeout=300,
        )
    except Exception:
        pass


def generate(
    model: str,
    prompt: str,
    system: str | None = None,
    timeout_s: int = 180,
    num_ctx: int = 8192,
) -> GenResult:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "10m",
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    }
    if system:
        payload["system"] = system

    start = time.perf_counter()
    ttft: float | None = None
    text_parts: list[str] = []
    tokens_out = 0
    error: str | None = None
    eval_count = 0
    eval_duration_ns = 0

    try:
        with httpx.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload, timeout=timeout_s) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                import json as _json
                try:
                    chunk = _json.loads(line)
                except Exception:
                    continue
                if ttft is None and chunk.get("response"):
                    ttft = (time.perf_counter() - start) * 1000
                if "response" in chunk:
                    text_parts.append(chunk["response"])
                    tokens_out += 1
                if chunk.get("done"):
                    eval_count = chunk.get("eval_count", tokens_out)
                    eval_duration_ns = chunk.get("eval_duration", 0)
                    break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = (time.perf_counter() - start) * 1000
    if eval_duration_ns > 0 and eval_count > 0:
        tps = eval_count / (eval_duration_ns / 1e9)
    elif duration_ms > 0 and tokens_out > 0:
        tps = tokens_out / (duration_ms / 1000)
    else:
        tps = 0.0

    return GenResult(
        text="".join(text_parts),
        ttft_ms=ttft,
        duration_ms=duration_ms,
        tokens_out=eval_count or tokens_out,
        tokens_per_sec=tps,
        error=error,
    )
