"""Sweep orchestrator: models × tasks → SQLite, then judging."""
from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# Timeout multipliers per size bucket. Large slow models need way more time
# than the task YAML defaults (which are tuned for small fast models).
BUCKET_TIMEOUT_MULT: dict[str, float] = {
    "<1B": 1.0,
    "<3B": 1.0,
    "<7B": 1.2,
    "<10B": 1.5,
    "<15B": 2.0,
    "<25B": 3.5,
    "<35B": 5.0,
    ">=35B": 6.0,
}
MIN_TIMEOUT_S: dict[str, int] = {
    "<15B": 240,
    "<25B": 480,
    "<35B": 720,   # 30B @ 4 tok/s × 500 tok ≈ 125s + TTFT + headroom
    ">=35B": 900,
}

# Time budget to allow for cold model load + prompt processing BEFORE the
# first token. Does not count against the task generation budget.
LOAD_BUDGET_S: dict[str, int] = {
    "<1B": 60,
    "<3B": 60,
    "<7B": 120,
    "<10B": 180,
    "<15B": 240,
    "<25B": 420,
    "<35B": 600,    # 30B cold load can take 60-90s on contended I/O
    ">=35B": 900,
}


def _scaled_timeout(task_timeout: int, bucket: str) -> int:
    mult = BUCKET_TIMEOUT_MULT.get(bucket, 1.0)
    scaled = int(task_timeout * mult)
    return max(scaled, MIN_TIMEOUT_S.get(bucket, 0))


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


def rejudge(
    sweep_id: str | None = None,
    judge_model: str = judge.SONNET,
    tag: str | None = None,
    overwrite: bool = False,
    parallelism: int = 6,
) -> str:
    """Re-grade stored model outputs with a (possibly different) judge.

    Does NOT re-run any models. Reads responses from `runs` and writes new
    rows into `scores` tagged with `judge_model`. Use `tag` to label the
    judge pass (e.g. "opus-review-2026-06") in the reasoning field.
    """
    from .tasks_loader import load_all as _load_all
    d = db()
    sid = sweep_id
    if not sid:
        rows = list(d.execute("SELECT id FROM sweeps ORDER BY started_at DESC LIMIT 1"))
        if not rows:
            raise RuntimeError("no sweeps to rejudge")
        sid = rows[0][0]

    all_tasks = {t.id: t for t in _load_all()}
    runs = list(d.execute(
        "SELECT id, task_id, response, error FROM runs WHERE sweep_id=?", [sid]
    ))
    console.print(f"[bold]rejudging sweep {sid}[/] with [cyan]{judge_model}[/] — {len(runs)} runs (parallelism={parallelism})")
    db_lock = threading.Lock()

    def _one(rid, task_id, response, error):
        if not overwrite:
            existing = list(d.execute(
                "SELECT id FROM scores WHERE run_id=? AND judge_model=?", [rid, judge_model]
            ))
            if existing:
                return None
        task = all_tasks.get(task_id)
        if task is None:
            return None
        if error or not (response or "").strip():
            return {"run_id": rid, "score": 1, "criteria_json": "[]", "reasoning": f"no output ({tag or ''})".strip(), "judge_model": judge_model}
        try:
            js = judge.score_absolute(task, response, model=judge_model)
            reasoning = js.reasoning if not tag else f"[{tag}] {js.reasoning}"
            return {
                "run_id": rid,
                "score": js.score,
                "criteria_json": js.model_dump_json(),
                "reasoning": reasoning,
                "judge_model": judge_model,
            }
        except Exception as e:
            return {"run_id": rid, "score": 1, "criteria_json": "[]", "reasoning": f"judge error: {e}", "judge_model": judge_model}

    with Progress(console=console) as prog:
        jt = prog.add_task("rejudge", total=len(runs))
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = [pool.submit(_one, *r) for r in runs]
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    with db_lock:
                        d["scores"].insert(row)
                prog.advance(jt)

    console.print(f"[bold green]rejudge done[/] sweep={sid} judge={judge_model}")
    return sid


def run_sweep(
    model_filter: list[str] | None = None,
    category_filter: str | None = None,
    smoke: bool = False,
    do_pairwise: bool = True,
    judge_abs: str = judge.SONNET,
    judge_pair: str = judge.SONNET,
    judge_tiebreak: str = judge.OPUS,
    judge_parallelism: int = 6,
    resume: str | None = None,
) -> str:
    d = db()
    if resume:
        sweep_id = resume
        row = d["sweeps"].get(sweep_id)
        console.print(f"[yellow]resuming sweep {sweep_id}[/]")
    else:
        sweep_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
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
    # pre-populate from DB for resume support
    for row in d.execute("SELECT id, model, task_id FROM runs WHERE sweep_id=?", [sweep_id]):
        run_ids_by_task_model[(row[2], row[1])] = row[0]
    already_done = len(run_ids_by_task_model)
    if already_done and resume:
        console.print(f"[yellow]found {already_done} existing runs in sweep, will skip those[/]")

    with Progress(console=console) as prog:
        gen_task = prog.add_task("generate", total=len(models) * len(tasks))
        for m in models:
            # skip model entirely if all its tasks are already done (resume)
            tasks_todo = [t for t in tasks if (t.id, m.name) not in run_ids_by_task_model]
            if not tasks_todo:
                console.print(f"  [dim]skip {m.name} — already complete[/]")
                prog.advance(gen_task, advance=len(tasks))
                continue
            load_budget = LOAD_BUDGET_S.get(m.bucket, 300)
            ollama.warmup(m.name, load_timeout_s=load_budget + 60)
            # advance for any tasks already done for this model
            prog.advance(gen_task, advance=len(tasks) - len(tasks_todo))
            for t in tasks_todo:
                timeout = _scaled_timeout(t.timeout_s, m.bucket)
                with RSSSampler() as s:
                    res = ollama.generate(
                        m.name, t.prompt, system=t.system,
                        timeout_s=timeout, load_budget_s=load_budget,
                    )
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

    # absolute judging — parallelized via thread pool (claude CLI is independent per call)
    console.print(f"[bold]judging (absolute) — parallelism={judge_parallelism}…[/]")
    db_lock = threading.Lock()

    # resume: find runs that already have a score with this judge
    already_scored: set[int] = set()
    for row in d.execute(
        "SELECT DISTINCT s.run_id FROM scores s JOIN runs r ON r.id=s.run_id WHERE r.sweep_id=? AND s.judge_model=?",
        [sweep_id, judge_abs],
    ):
        already_scored.add(row[0])

    def _judge_one(t, m):
        rid = run_ids_by_task_model[(t.id, m.name)]
        if rid in already_scored:
            return rid, None
        run = d["runs"].get(rid)
        if run.get("error") or not run.get("response", "").strip():
            return rid, {"run_id": rid, "score": 1, "criteria_json": "[]", "reasoning": "no output", "judge_model": judge_abs}
        try:
            js = judge.score_absolute(t, run["response"], model=judge_abs)
            return rid, {
                "run_id": rid,
                "score": js.score,
                "criteria_json": js.model_dump_json(),
                "reasoning": js.reasoning,
                "judge_model": judge_abs,
            }
        except Exception as e:
            return rid, {"run_id": rid, "score": 1, "criteria_json": "[]", "reasoning": f"judge error: {e}", "judge_model": judge_abs}

    jobs = [(t, m) for t in tasks for m in models]
    with Progress(console=console) as prog:
        jt = prog.add_task("judge", total=len(jobs))
        with ThreadPoolExecutor(max_workers=judge_parallelism) as pool:
            futures = [pool.submit(_judge_one, t, m) for t, m in jobs]
            for fut in as_completed(futures):
                _, row = fut.result()
                if row is not None:
                    with db_lock:
                        d["scores"].insert(row)
                prog.advance(jt)

    # pairwise on top quartile per category — also parallelized
    if do_pairwise and len(models) >= 2:
        console.print(f"[bold]judging (pairwise, top quartile per category) — parallelism={judge_parallelism}…[/]")
        by_cat_model: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in d.execute("SELECT r.category, r.model, s.score FROM runs r JOIN scores s ON s.run_id=r.id WHERE r.sweep_id=?", [sweep_id]):
            by_cat_model[(row[0], row[1])].append(row[2])
        categories = {c for c, _ in by_cat_model}
        pair_jobs = []
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
                        pair_jobs.append((t, top_models[i], top_models[j]))

        def _pair_one(t, ma, mb):
            ra = d["runs"].get(run_ids_by_task_model[(t.id, ma)])
            rb = d["runs"].get(run_ids_by_task_model[(t.id, mb)])
            if not ra["response"].strip() or not rb["response"].strip():
                return None
            try:
                v = judge.pairwise(t, ra["response"], rb["response"], model=judge_pair)
                return {
                    "sweep_id": sweep_id,
                    "task_id": t.id,
                    "model_a": ma,
                    "model_b": mb,
                    "winner": v.winner,
                    "judge_model": judge_pair,
                    "reasoning": v.reasoning,
                }
            except Exception as e:
                console.print(f"[red]pairwise error {ma} vs {mb} on {t.id}: {e}[/]")
                return None

        if pair_jobs:
            with Progress(console=console) as prog:
                pt = prog.add_task("pairwise", total=len(pair_jobs))
                with ThreadPoolExecutor(max_workers=judge_parallelism) as pool:
                    futures = [pool.submit(_pair_one, t, a, b) for t, a, b in pair_jobs]
                    for fut in as_completed(futures):
                        row = fut.result()
                        if row:
                            with db_lock:
                                d["pairwise"].insert(row)
                        prog.advance(pt)

    d["sweeps"].update(sweep_id, {"finished_at": dt.datetime.now().isoformat()})
    console.print(f"[bold green]done:[/] sweep {sweep_id}")
    return sweep_id
