"""OpenAI-compatible streaming client for LM Studio / llama-server / mlx_lm.server.

Mirrors bench.ollama's GenResult + generate/warmup/unload signatures so the
runner can dispatch to either backend by model-name prefix.

Default base URL is LM Studio's (http://localhost:1234/v1). Override with
$OPENAI_BASE_URL. No API key needed for local servers; send a dummy one.
"""
from __future__ import annotations

import json as _json
import os
import time

import httpx

from .ollama import GenResult

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:1234/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "sk-local")


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def list_models() -> list[dict]:
    try:
        r = httpx.get(f"{BASE_URL}/models", headers=_headers(), timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def warmup(model: str, load_timeout_s: int = 600) -> None:
    """LM Studio auto-loads on first request; send a tiny prompt to force it."""
    try:
        httpx.post(
            f"{BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "stream": False,
            },
            timeout=load_timeout_s,
        )
    except Exception:
        pass


def unload(model: str) -> None:
    """No standard unload in OpenAI API. LM Studio keeps model loaded; that's fine."""
    pass


def generate(
    model: str,
    prompt: str,
    system: str | None = None,
    timeout_s: int = 180,
    num_ctx: int = 8192,
    load_budget_s: int = 600,
) -> GenResult:
    """Stream from /v1/chat/completions with TTFT-aware dual-timeout, matching
    bench.ollama.generate's semantics."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
    }

    per_read_s = max(load_budget_s, timeout_s) + 30
    http_timeout = httpx.Timeout(connect=30.0, read=float(per_read_s), write=30.0, pool=30.0)

    start = time.perf_counter()
    gen_start: float | None = None
    ttft: float | None = None
    text_parts: list[str] = []
    tokens_out = 0
    error: str | None = None

    try:
        with httpx.stream(
            "POST",
            f"{BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=http_timeout,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if gen_start is None:
                    if (time.perf_counter() - start) > load_budget_s:
                        error = f"load timeout: no first token within {load_budget_s}s"
                        break
                else:
                    if (time.perf_counter() - gen_start) > timeout_s:
                        error = f"generation timeout: exceeded {timeout_s}s after first token"
                        break
                if not line:
                    continue
                # SSE: "data: {...}" or "data: [DONE]"
                if line.startswith("data: "):
                    data = line[6:]
                else:
                    data = line
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data)
                except Exception:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                # Capture content + reasoning_content (DeepSeek/LM Studio convention) +
                # reasoning (some other servers) + tool_calls. Mirrors the Ollama fix.
                raw_content = delta.get("content") or ""
                raw_reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                raw_tools = delta.get("tool_calls")
                content = ""
                if raw_reasoning:
                    content += raw_reasoning
                if raw_content:
                    content += raw_content
                if raw_tools:
                    content += "\n[tool_calls] " + _json.dumps(raw_tools)
                if ttft is None and content:
                    now = time.perf_counter()
                    ttft = (now - start) * 1000
                    gen_start = now
                if content:
                    text_parts.append(content)
                    tokens_out += 1
                if choices[0].get("finish_reason"):
                    break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = (time.perf_counter() - start) * 1000

    # OpenAI-compatible endpoints don't return eval_count/eval_duration like
    # Ollama does, so `tokens_out` is a chunk count (unreliable — one chunk can
    # contain 1 char or 50).  LM Studio *does* return a `usage` object in the
    # final SSE chunk, but not all servers do.  As a robust fallback, estimate
    # real token count from character length (~4 chars/token for English).
    full_text = "".join(text_parts)
    estimated_tokens = max(len(full_text) // 4, tokens_out)

    if duration_ms > 0 and estimated_tokens > 0 and gen_start is not None:
        gen_ms = (time.perf_counter() - gen_start) * 1000
        tps = estimated_tokens / (gen_ms / 1000) if gen_ms > 0 else 0.0
    else:
        tps = 0.0

    return GenResult(
        text=full_text,
        ttft_ms=ttft,
        duration_ms=duration_ms,
        tokens_out=estimated_tokens,
        tokens_per_sec=tps,
        error=error,
    )
