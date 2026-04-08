"""Markdown leaderboard generation from SQLite results."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path

from .db import db
from .pairwise import bradley_terry, to_elo

REPORTS = Path(__file__).resolve().parent.parent / "results" / "reports"


def _latest_sweep() -> str | None:
    d = db()
    rows = list(d.execute("SELECT id FROM sweeps ORDER BY started_at DESC LIMIT 1"))
    return rows[0][0] if rows else None


def generate(sweep_id: str | None = None) -> Path:
    d = db()
    sid = sweep_id or _latest_sweep()
    if not sid:
        raise RuntimeError("no sweeps in DB")
    REPORTS.mkdir(parents=True, exist_ok=True)

    rows = list(d.execute(
        """
        SELECT r.model, r.bucket, r.category, r.tokens_per_sec, r.ttft_ms, r.peak_rss_mb, s.score
        FROM runs r JOIN scores s ON s.run_id=r.id
        WHERE r.sweep_id=?
        """,
        [sid],
    ))

    # aggregate
    by_model: dict[str, dict] = defaultdict(lambda: {"scores": [], "tps": [], "ttft": [], "rss": [], "bucket": "?", "per_cat": defaultdict(list)})
    for model, bucket, cat, tps, ttft, rss, score in rows:
        m = by_model[model]
        m["bucket"] = bucket
        m["scores"].append(score)
        m["tps"].append(tps or 0)
        m["ttft"].append(ttft or 0)
        m["rss"].append(rss or 0)
        m["per_cat"][cat].append(score)

    def avg(xs): return sum(xs) / len(xs) if xs else 0.0

    summary = []
    for model, m in by_model.items():
        qs = avg(m["scores"])
        tps = avg(m["tps"])
        composite = (qs / 5.0) * tps
        summary.append({
            "model": model,
            "bucket": m["bucket"],
            "quality": qs,
            "tps": tps,
            "ttft_ms": avg(m["ttft"]),
            "peak_rss_gb": avg(m["rss"]) / 1024,
            "composite": composite,
            "per_cat": {k: avg(v) for k, v in m["per_cat"].items()},
        })

    lines: list[str] = []
    lines.append(f"# Bench report — sweep `{sid}`\n")
    lines.append(f"_generated {dt.datetime.now().isoformat(timespec='seconds')}_\n")

    lines.append("## Overall leaderboard\n")
    lines.append("| Rank | Model | Bucket | Quality (1-5) | Tok/s | TTFT (ms) | Peak RSS (GB) | Composite (qual × tok/s) |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|")
    for i, s in enumerate(sorted(summary, key=lambda x: -x["quality"]), 1):
        lines.append(f"| {i} | `{s['model']}` | {s['bucket']} | {s['quality']:.2f} | {s['tps']:.1f} | {s['ttft_ms']:.0f} | {s['peak_rss_gb']:.1f} | {s['composite']:.2f} |")

    # per-bucket leaderboards (fairness)
    lines.append("\n## Per-bucket leaderboards (fair comparison)\n")
    by_bucket: dict[str, list] = defaultdict(list)
    for s in summary:
        by_bucket[s["bucket"]].append(s)
    bucket_order = ["<1B", "<3B", "<7B", "<10B", "<15B", "<25B", "<35B", ">=35B"]
    for b in bucket_order:
        if b not in by_bucket:
            continue
        lines.append(f"### {b}\n")
        lines.append("| Model | Quality | Tok/s | Composite |")
        lines.append("|---|---:|---:|---:|")
        for s in sorted(by_bucket[b], key=lambda x: -x["quality"]):
            lines.append(f"| `{s['model']}` | {s['quality']:.2f} | {s['tps']:.1f} | {s['composite']:.2f} |")
        lines.append("")

    # per category
    cats = sorted({c for s in summary for c in s["per_cat"]})
    lines.append("## Per-category quality\n")
    header = "| Model | Bucket | " + " | ".join(cats) + " |"
    sep = "|---|---|" + "|".join(["---:"] * len(cats)) + "|"
    lines.append(header)
    lines.append(sep)
    for s in sorted(summary, key=lambda x: -x["quality"]):
        row = f"| `{s['model']}` | {s['bucket']} | " + " | ".join(f"{s['per_cat'].get(c, 0):.2f}" for c in cats) + " |"
        lines.append(row)

    # pairwise Elo
    pw_rows = list(d.execute("SELECT model_a, model_b, winner FROM pairwise WHERE sweep_id=?", [sid]))
    if pw_rows:
        strengths = bradley_terry([(a, b, w) for a, b, w in pw_rows])
        elo = to_elo(strengths)
        lines.append("\n## Pairwise Elo (top quartile per category)\n")
        lines.append("| Model | Elo |")
        lines.append("|---|---:|")
        for m, e in sorted(elo.items(), key=lambda x: -x[1]):
            lines.append(f"| `{m}` | {e:.0f} |")

    out = REPORTS / f"{sid}.md"
    out.write_text("\n".join(lines))
    return out
