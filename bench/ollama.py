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


def warmup(model: str, load_timeout_s: int = 600) -> None:
    """Force model into memory. Long timeout since cold loads of 30B models
    from disk can take 30-90s on spinning or contended I/O."""
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": "hi", "stream": False, "keep_alive": "10m"},
            timeout=load_timeout_s,
        )
    except Exception:
        pass


def generate(
    model: str,
    prompt: str,
    system: str | None = None,
    timeout_s: int = 180,
    num_ctx: int = 8192,
    load_budget_s: int = 600,
) -> GenResult:
    """Stream from Ollama's /api/chat endpoint with TWO separate timeouts:

    - `load_budget_s`: how long we'll wait for the first token (covers cold
      model load + prompt processing). Does NOT count against the task budget.
    - `timeout_s`: actual task generation budget, counted ONLY from TTFT onward.
      If the model generates for longer than this after producing its first
      token, we kill the stream.

    Uses /api/chat (not /api/generate) so that chat-template-only GGUFs
    (models that use {{ range .Messages }} with no .Prompt fallback) work.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": "10m",
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    }

    # httpx per-read timeout only — no total timeout. Connection/read bound
    # by the larger of load_budget and task timeout, with generous slack.
    per_read_s = max(load_budget_s, timeout_s) + 30
    http_timeout = httpx.Timeout(connect=30.0, read=float(per_read_s), write=30.0, pool=30.0)

    start = time.perf_counter()
    gen_start: float | None = None
    ttft: float | None = None
    text_parts: list[str] = []
    tokens_out = 0
    error: str | None = None
    eval_count = 0
    eval_duration_ns = 0

    try:
        with httpx.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload, timeout=http_timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                # Pre-TTFT: enforce load budget (model loading + prompt processing)
                if gen_start is None:
                    if (time.perf_counter() - start) > load_budget_s:
                        error = f"load timeout: no first token within {load_budget_s}s"
                        break
                else:
                    # Post-TTFT: enforce task generation budget from first token
                    if (time.perf_counter() - gen_start) > timeout_s:
                        error = f"generation timeout: exceeded {timeout_s}s after first token"
                        break
                if not line:
                    continue
                import json as _json
                try:
                    chunk = _json.loads(line)
                except Exception:
                    continue
                # /api/chat returns {"message": {"role": "assistant", "content": "..."}, ...}
                content = ""
                msg = chunk.get("message") or {}
                if isinstance(msg, dict):
                    content = msg.get("content", "") or ""
                if ttft is None and content:
                    now = time.perf_counter()
                    ttft = (now - start) * 1000
                    gen_start = now
                if content:
                    text_parts.append(content)
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
