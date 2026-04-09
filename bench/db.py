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
    if "tournaments" not in d.table_names():
        d["tournaments"].create({
            "id": str,
            "created_at": str,
            "mode": str,        # round_robin | bracket
            "filter_bucket": str,
            "filter_category": str,
            "top_n": int,
            "candidates_json": str,
            "tag": str,
        }, pk="id")
    if "tournament_matches" not in d.table_names():
        d["tournament_matches"].create({
            "id": int,
            "tournament_id": str,
            "task_id": str,
            "model_a": str,
            "model_b": str,
            "winner": str,
            "judge_model": str,
            "reasoning": str,
            "round": int,
        }, pk="id")
