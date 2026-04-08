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
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # walk all {...} blobs by balanced braces and try each
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            in_str = False
            esc = False
            for j in range(i, len(text)):
                c = text[j]
                if esc:
                    esc = False
                    continue
                if c == "\\":
                    esc = True
                    continue
                if c == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        blob = text[i : j + 1]
                        try:
                            return json.loads(blob)
                        except json.JSONDecodeError:
                            break
            i = j + 1
        else:
            i += 1
    raise ValueError(f"no parseable JSON object in: {text[:200]}")


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
