"""Sweep orchestrator: models × tasks → SQLite, then judging."""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from . import judge, ollama, registry
from .db import db
from .pairwise import bradley_terry, to_elo
from .sampler import RSSSampler
from .schema import Task
from .tasks_loader import load_all

console = Console()


def _size_from_ollama(info: dict) -> float:
    details = info.get("details") or {}
    ps = details.get("parameter_size") or ""
    if not ps:
        return 0.0
    s = ps.upper().replace("B", "").replace("M", "")
    try:
        val = float(s)
    except ValueError:
        return 0.0
    if "M" in ps.upper() and "B" not in ps.upper():
        val = val / 1000
    return val


def discover_models(filter_names: list[str] | None = None) -> list[registry.ModelInfo]:
    models = []
    for m in ollama.list_models():
        name = m["name"]
        if not registry.should_include(name):
            continue
        if filter_names and name not in filter_names:
            continue
        params_b = _size_from_ollama(m)
        details = m.get("details") or {}
        info = registry.ModelInfo(
            name=name,
            params_b=params_b,
            bucket=registry.bucket_for(params_b),
            family=details.get("family", "?"),
            quant=details.get("quantization_level", "?"),
        )
        models.append(info)
    # sort by size asc
    models.sort(key=lambda x: x.params_b)
    return models


def run_sweep(
    model_filter: list[str] | None = None,
    category_filter: str | None = None,
    smoke: bool = False,
    do_pairwise: bool = True,
    judge_abs: str = judge.SONNET,
    judge_pair: str = judge.SONNET,
    judge_tiebreak: str = judge.OPUS,
) -> str:
    sweep_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = db()
    d["sweeps"].insert({"id": sweep_id, "started_at": dt.datetime.now().isoformat(), "finished_at": "", "notes": "smoke" if smoke else ""})

    models = discover_models(model_filter)
    tasks = load_all(category_filter)
    if smoke:
        # 1 task per category
        seen = set()
        picked = []
        for t in tasks:
            if t.category not in seen:
                picked.append(t)
                seen.add(t.category)
        tasks = picked

    console.print(f"[bold cyan]sweep {sweep_id}[/] — {len(models)} models × {len(tasks)} tasks = {len(models)*len(tasks)} runs")
    for m in models:
        console.print(f"  • {m.name:32} {m.params_b:5.1f}B  [{m.bucket}]  ~{m.approx_ram_gb:.1f}GB")

    run_ids_by_task_model: dict[tuple[str, str], int] = {}

    with Progress(console=console) as prog:
        gen_task = prog.add_task("generate", total=len(models) * len(tasks))
        for m in models:
            ollama.warmup(m.name)
            for t in tasks:
                with RSSSampler() as s:
                    res = ollama.generate(m.name, t.prompt, system=t.system, timeout_s=t.timeout_s)
                row = {
                    "sweep_id": sweep_id,
                    "model": m.name,
                    "bucket": m.bucket,
                    "task_id": t.id,
                    "category": t.category,
                    "response": res.text,
                    "ttft_ms": res.ttft_ms,
                    "duration_ms": res.duration_ms,
                    "tokens_out": res.tokens_out,
                    "tokens_per_sec": res.tokens_per_sec,
                    "peak_rss_mb": s.peak_mb,
                    "error": res.error,
                }
                rid = d["runs"].insert(row).last_pk
                run_ids_by_task_model[(t.id, m.name)] = rid
                prog.advance(gen_task)
            ollama.unload(m.name)

    # absolute judging
    console.print("[bold]judging (absolute)…[/]")
    with Progress(console=console) as prog:
        jt = prog.add_task("judge", total=len(models) * len(tasks))
        for t in tasks:
            for m in models:
                rid = run_ids_by_task_model[(t.id, m.name)]
                run = d["runs"].get(rid)
                if run.get("error") or not run.get("response", "").strip():
                    d["scores"].insert({"run_id": rid, "score": 1, "criteria_json": "[]", "reasoning": "no output", "judge_model": judge_abs})
                    prog.advance(jt)
                    continue
                try:
                    js = judge.score_absolute(t, run["response"], model=judge_abs)
                    d["scores"].insert({
                        "run_id": rid,
                        "score": js.score,
                        "criteria_json": js.model_dump_json(),
                        "reasoning": js.reasoning,
                        "judge_model": judge_abs,
                    })
                except Exception as e:
                    d["scores"].insert({"run_id": rid, "score": 1, "criteria_json": "[]", "reasoning": f"judge error: {e}", "judge_model": judge_abs})
                prog.advance(jt)

    # pairwise on top quartile per category
    if do_pairwise and len(models) >= 2:
        console.print("[bold]judging (pairwise, top quartile per category)…[/]")
        # compute avg score per (category, model)
        by_cat_model: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in d.execute("SELECT r.category, r.model, s.score FROM runs r JOIN scores s ON s.run_id=r.id WHERE r.sweep_id=?", [sweep_id]):
            by_cat_model[(row[0], row[1])].append(row[2])
        categories = {c for c, _ in by_cat_model}
        for cat in categories:
            ranked = sorted(
                [(m, sum(v)/len(v)) for (c, m), v in by_cat_model.items() if c == cat],
                key=lambda x: -x[1],
            )
            top_k = max(2, len(ranked) // 4)
            top_models = [m for m, _ in ranked[:top_k]]
            cat_tasks = [t for t in tasks if t.category == cat and t.pairwise_eligible]
            for t in cat_tasks:
                for i in range(len(top_models)):
                    for j in range(i + 1, len(top_models)):
                        ma, mb = top_models[i], top_models[j]
                        ra = d["runs"].get(run_ids_by_task_model[(t.id, ma)])
                        rb = d["runs"].get(run_ids_by_task_model[(t.id, mb)])
                        if not ra["response"].strip() or not rb["response"].strip():
                            continue
                        try:
                            v = judge.pairwise(t, ra["response"], rb["response"], model=judge_pair)
                            d["pairwise"].insert({
                                "sweep_id": sweep_id,
                                "task_id": t.id,
                                "model_a": ma,
                                "model_b": mb,
                                "winner": v.winner,
                                "judge_model": judge_pair,
                                "reasoning": v.reasoning,
                            })
                        except Exception as e:
                            console.print(f"[red]pairwise error {ma} vs {mb} on {t.id}: {e}[/]")

    d["sweeps"].update(sweep_id, {"finished_at": dt.datetime.now().isoformat()})
    console.print(f"[bold green]done:[/] sweep {sweep_id}")
    return sweep_id
