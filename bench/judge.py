"""Claude-as-judge via the `claude` CLI.

Uses `claude -p --output-format json` so we can reliably parse results
without burning an API key. Sonnet is default; Opus for tiebreaks.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .schema import JudgeScore, PairwiseVerdict, Task

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-6"


def _run_claude(prompt: str, model: str, timeout: int = 180) -> str:
    """Invoke `claude -p` non-interactively and return the raw response text."""
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({proc.returncode}): {proc.stderr[:400]}")
    try:
        envelope = json.loads(proc.stdout)
        return envelope.get("result", proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout


def _extract_json(text: str) -> dict:
    text = text.strip()
    # strip code fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # find first {...} balanced blob
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"no JSON found in judge output: {text[:200]}")


def score_absolute(task: Task, response: str, model: str = SONNET) -> JudgeScore:
    template = (PROMPTS / "judge_rubric.md").read_text()
    rubric_str = "\n".join(f"- (weight {r.weight}) {r.criterion}" for r in task.rubric)
    ref = task.reference_solution or "(none provided)"
    prompt = template.format(
        task_id=task.id,
        category=task.category,
        task_prompt=task.prompt,
        rubric=rubric_str,
        reference=ref,
        response=response,
    )
    raw = _run_claude(prompt, model=model)
    data = _extract_json(raw)
    # normalize "pass" key
    for c in data.get("criteria", []):
        if "pass_" in c and "pass" not in c:
            c["pass"] = c.pop("pass_")
    return JudgeScore.model_validate(data)


def pairwise(task: Task, response_a: str, response_b: str, model: str = SONNET) -> PairwiseVerdict:
    template = (PROMPTS / "judge_pairwise.md").read_text()
    prompt = template.format(
        task_prompt=task.prompt,
        response_a=response_a,
        response_b=response_b,
    )
    raw = _run_claude(prompt, model=model)
    data = _extract_json(raw)
    return PairwiseVerdict.model_validate(data)
