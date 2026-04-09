"""Cross-sweep tournaments: head-to-head pairwise across all stored outputs.

Unlike the per-sweep pairwise (which only compares models within one run), a
tournament pulls the best candidates from ALL sweeps in the DB and runs them
against each other on their shared task set. Uses already-stored model
responses — no regeneration.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress

from . import judge
from .db import db
from .pairwise import bradley_terry, to_elo
from .schema import Task
from .tasks_loader import load_all

console = Console()


def _select_candidates(
    d,
    bucket: str | None = None,
    category: str | None = None,
    top_n: int = 8,
    min_runs: int = 5,
) -> list[tuple[str, float, int]]:
    """Pick top-N models by avg quality across ALL sweeps, using the latest
    judge score per run. Returns list of (model, avg_quality, run_count).

    Filters:
    - bucket: restrict to a size bucket (e.g. "<10B")
    - category: restrict scoring to one task category
    - min_runs: require at least N scored runs to be eligible
    """
    where = []
    params: list = []
    if bucket:
        where.append("r.bucket = ?")
        params.append(bucket)
    if category:
        where.append("r.category = ?")
        params.append(category)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    q = f"""
    SELECT r.model, AVG(s.score) AS q, COUNT(s.id) AS n
    FROM runs r
    JOIN scores s ON s.id = (
        SELECT MAX(s2.id) FROM scores s2 WHERE s2.run_id = r.id
    )
    {where_sql}
    GROUP BY r.model
    HAVING n >= ?
    ORDER BY q DESC
    LIMIT ?
    """
    params.extend([min_runs, top_n])
    return [(row[0], row[1], row[2]) for row in d.execute(q, params)]


def _shared_tasks(d, models: list[str], category: str | None = None) -> list[str]:
    """Return task IDs that EVERY selected model has a run for."""
    placeholders = ",".join("?" * len(models))
    cat_clause = "AND r.category = ?" if category else ""
    cat_params = [category] if category else []
    q = f"""
    SELECT r.task_id
    FROM runs r
    WHERE r.model IN ({placeholders}) {cat_clause}
    GROUP BY r.task_id
    HAVING COUNT(DISTINCT r.model) = ?
    """
    params = list(models) + cat_params + [len(models)]
    return [row[0] for row in d.execute(q, params)]


def _best_run_for(d, model: str, task_id: str) -> dict | None:
    """Latest non-errored run for (model, task) across all sweeps."""
    rows = list(d.execute(
        """
        SELECT id, response, error, sweep_id
        FROM runs
        WHERE model = ? AND task_id = ?
          AND (error IS NULL OR error = '')
          AND response IS NOT NULL AND response != ''
        ORDER BY id DESC LIMIT 1
        """,
        [model, task_id],
    ))
    if not rows:
        return None
    return {"id": rows[0][0], "response": rows[0][1], "error": rows[0][2], "sweep_id": rows[0][3]}


def run_tournament(
    bucket: str | None = None,
    category: str | None = None,
    top_n: int = 8,
    mode: str = "round_robin",
    judge_model: str = judge.SONNET,
    tiebreak_model: str = judge.OPUS,
    parallelism: int = 6,
    tag: str | None = None,
) -> str:
    """Run a cross-sweep tournament. Returns tournament_id."""
    d = db()
    tournament_id = "trn-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

    # 1. Select candidates
    candidates = _select_candidates(d, bucket=bucket, category=category, top_n=top_n)
    if len(candidates) < 2:
        raise RuntimeError(f"not enough candidates: {candidates}")

    models = [c[0] for c in candidates]
    console.print(f"[bold cyan]tournament {tournament_id}[/]")
    console.print(f"  mode: {mode}  •  bucket: {bucket or 'any'}  •  category: {category or 'any'}  •  top_n: {top_n}")
    console.print("\n[bold]Seeded candidates:[/]")
    for i, (m, q, n) in enumerate(candidates, 1):
        console.print(f"  {i:2}. {m:60} quality={q:.2f}  (n={n})")

    # 2. Find shared tasks
    tasks_ids = _shared_tasks(d, models, category=category)
    if not tasks_ids:
        raise RuntimeError("no shared tasks — candidates don't overlap on any task")
    console.print(f"\n[dim]shared tasks: {len(tasks_ids)}[/]")

    # Load task objects for judging
    all_tasks = {t.id: t for t in load_all()}
    tasks = [all_tasks[tid] for tid in tasks_ids if tid in all_tasks]
    if not tasks:
        raise RuntimeError("shared tasks missing from task loader")

    # 3. Record tournament
    d["tournaments"].insert({
        "id": tournament_id,
        "created_at": dt.datetime.now().isoformat(),
        "mode": mode,
        "filter_bucket": bucket or "",
        "filter_category": category or "",
        "top_n": top_n,
        "candidates_json": json.dumps(candidates),
        "tag": tag or "",
    })

    # 4. Build match list
    matches: list[tuple[Task, str, str, int]] = []
    if mode == "round_robin":
        for t in tasks:
            for i in range(len(models)):
                for j in range(i + 1, len(models)):
                    matches.append((t, models[i], models[j], 1))
    elif mode == "bracket":
        # single-elimination, seeds pair as 1-vs-N, 2-vs-N-1, …
        # each match is played over ALL shared tasks, winner = model with more task wins
        rnd = 1
        current = list(models)
        while len(current) > 1:
            pairs = []
            n = len(current)
            for i in range(n // 2):
                pairs.append((current[i], current[n - 1 - i]))
            # odd man bye
            if n % 2 == 1:
                pairs.append((current[n // 2], None))
            # Queue all pair-task matches for this round
            round_matches = []
            for a, b in pairs:
                if b is None:
                    continue
                for t in tasks:
                    round_matches.append((t, a, b, rnd))
            matches.extend(round_matches)
            # For now, we only queue round 1 matches — round 2+ needs results first
            break
    else:
        raise ValueError(f"unknown mode: {mode}")

    console.print(f"[dim]total matches to judge: {len(matches)}[/]")

    # 5. Judge matches in parallel
    db_lock = threading.Lock()
    match_rows: list[dict] = []

    def _judge_match(t: Task, ma: str, mb: str, rnd: int):
        ra = _best_run_for(d, ma, t.id)
        rb = _best_run_for(d, mb, t.id)
        if not ra or not rb:
            return None
        if not (ra["response"] or "").strip() or not (rb["response"] or "").strip():
            return None
        try:
            v = judge.pairwise(t, ra["response"], rb["response"], model=judge_model)
            return {
                "tournament_id": tournament_id,
                "task_id": t.id,
                "model_a": ma,
                "model_b": mb,
                "winner": v.winner,
                "judge_model": judge_model,
                "reasoning": v.reasoning,
                "round": rnd,
            }
        except Exception as e:
            console.print(f"[red]match error {ma} vs {mb} on {t.id}: {e}[/]")
            return None

    with Progress(console=console) as prog:
        pt = prog.add_task("tournament", total=len(matches))
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = [pool.submit(_judge_match, *m) for m in matches]
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    with db_lock:
                        d["tournament_matches"].insert(row)
                        match_rows.append(row)
                prog.advance(pt)

    # 6. Compute standings via Bradley-Terry
    pairs = [(m["model_a"], m["model_b"], m["winner"]) for m in match_rows]
    strengths = bradley_terry(pairs)
    elo = to_elo(strengths)

    # Per-model win/loss/tie counts
    wins: dict[str, int] = defaultdict(int)
    losses: dict[str, int] = defaultdict(int)
    ties: dict[str, int] = defaultdict(int)
    for m in match_rows:
        if m["winner"] == "A":
            wins[m["model_a"]] += 1
            losses[m["model_b"]] += 1
        elif m["winner"] == "B":
            wins[m["model_b"]] += 1
            losses[m["model_a"]] += 1
        else:
            ties[m["model_a"]] += 1
            ties[m["model_b"]] += 1

    console.print("\n[bold]🏆 Tournament standings[/]")
    console.print(f"{'rank':<4} {'model':<60} {'Elo':>6}  {'W':>3}-{'L':<3}-{'T':<3}  base_quality")
    standings = sorted(elo.items(), key=lambda x: -x[1])
    seed_quality = {c[0]: c[1] for c in candidates}
    for i, (m, e) in enumerate(standings, 1):
        console.print(f"{i:<4} {m:<60} {e:6.0f}  {wins[m]:>3}-{losses[m]:<3}-{ties[m]:<3}  {seed_quality.get(m, 0):.2f}")

    console.print(f"\n[bold green]tournament done[/] — {len(match_rows)} matches, id: {tournament_id}")
    return tournament_id
