"""SQLite persistence for sweeps, runs, scores, pairwise verdicts."""
from __future__ import annotations

from pathlib import Path

import sqlite_utils

DB_PATH = Path(__file__).resolve().parent.parent / "results" / "bench.sqlite"


def db() -> sqlite_utils.Database:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    d = sqlite_utils.Database(DB_PATH)
    _init(d)
    return d


def _init(d: sqlite_utils.Database) -> None:
    if "sweeps" not in d.table_names():
        d["sweeps"].create({
            "id": str,
            "started_at": str,
            "finished_at": str,
            "notes": str,
        }, pk="id")
    if "runs" not in d.table_names():
        d["runs"].create({
            "id": int,
            "sweep_id": str,
            "model": str,
            "bucket": str,
            "task_id": str,
            "category": str,
            "response": str,
            "ttft_ms": float,
            "duration_ms": float,
            "tokens_out": int,
            "tokens_per_sec": float,
            "peak_rss_mb": float,
            "error": str,
        }, pk="id")
    if "scores" not in d.table_names():
        d["scores"].create({
            "id": int,
            "run_id": int,
            "score": int,
            "criteria_json": str,
            "reasoning": str,
            "judge_model": str,
        }, pk="id")
    if "pairwise" not in d.table_names():
        d["pairwise"].create({
            "id": int,
            "sweep_id": str,
            "task_id": str,
            "model_a": str,
            "model_b": str,
            "winner": str,      # "A" | "B" | "tie"
            "judge_model": str,
            "reasoning": str,
        }, pk="id")
