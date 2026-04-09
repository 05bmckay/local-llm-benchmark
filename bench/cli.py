from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import registry, runner
from .report import generate as gen_report
from .tasks_loader import load_all

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def models():
    """List discovered Ollama models with bucket + RAM estimate."""
    ms = runner.discover_models()
    t = Table(title="Ollama models")
    t.add_column("Name"); t.add_column("Params"); t.add_column("Bucket"); t.add_column("Quant"); t.add_column("~RAM (GB)")
    for m in ms:
        t.add_row(registry.display_name(m.name), f"{m.params_b:.1f}B", m.bucket, m.quant, f"{m.approx_ram_gb:.1f}")
    console.print(t)


@app.command()
def tasks(category: str = typer.Option(None)):
    """List tasks."""
    ts = load_all(category)
    t = Table(title=f"Tasks ({len(ts)})")
    t.add_column("ID"); t.add_column("Category"); t.add_column("Diff"); t.add_column("Tags")
    for task in ts:
        t.add_row(task.id, task.category, str(task.difficulty), ",".join(task.tags))
    console.print(t)


@app.command()
def run(
    models: str = typer.Option(None, help="comma-separated model filter"),
    category: str = typer.Option(None),
    smoke: bool = typer.Option(False),
    no_pairwise: bool = typer.Option(False),
    judge_parallelism: int = typer.Option(6, help="parallel judge CLI calls"),
    resume: str = typer.Option(None, help="resume a previously-killed sweep by ID"),
):
    """Run a sweep."""
    model_filter = [m.strip() for m in models.split(",")] if models else None
    sid = runner.run_sweep(
        model_filter=model_filter,
        category_filter=category,
        smoke=smoke,
        do_pairwise=not no_pairwise,
        judge_parallelism=judge_parallelism,
        resume=resume,
    )
    path = gen_report(sid)
    console.print(f"[green]report:[/] {path}")


@app.command()
def report(
    sweep_id: str = typer.Option(None),
    judge: str = typer.Option(None, help="Filter to a specific judge_model pass"),
):
    """Regenerate report for a sweep (default: latest, using most recent judge pass)."""
    path = gen_report(sweep_id, judge_model=judge)
    console.print(f"[green]report:[/] {path}")


@app.command()
def rejudge(
    sweep_id: str = typer.Option(None, help="Sweep to rejudge (default: latest)"),
    judge_model: str = typer.Option("claude-sonnet-4-6", help="Claude model to use as judge"),
    tag: str = typer.Option(None, help="Label for this judge pass"),
    overwrite: bool = typer.Option(False, help="Re-score even if this judge already scored"),
):
    """Re-grade stored model outputs with a different judge. No model re-runs."""
    from . import runner
    sid = runner.rejudge(sweep_id=sweep_id, judge_model=judge_model, tag=tag, overwrite=overwrite)
    path = gen_report(sid, judge_model=judge_model)
    console.print(f"[green]report:[/] {path}")


@app.command()
def sweeps():
    """List all sweeps in the DB."""
    from .db import db as _db
    d = _db()
    t = Table(title="Sweeps")
    t.add_column("ID"); t.add_column("Started"); t.add_column("Finished"); t.add_column("Runs"); t.add_column("Notes")
    for row in d.execute("SELECT s.id, s.started_at, s.finished_at, COUNT(r.id), s.notes FROM sweeps s LEFT JOIN runs r ON r.sweep_id=s.id GROUP BY s.id ORDER BY s.started_at DESC"):
        t.add_row(row[0], row[1][:19], (row[2] or "")[:19], str(row[3]), row[4] or "")
    console.print(t)


@app.command()
def tournament(
    bucket: str = typer.Option(None, help="Size bucket filter (e.g. '<10B')"),
    category: str = typer.Option(None, help="Task category filter"),
    top_n: int = typer.Option(8, help="Number of top seeded candidates"),
    mode: str = typer.Option("round_robin", help="round_robin | bracket"),
    parallelism: int = typer.Option(6),
    tag: str = typer.Option(None, help="Label for this tournament"),
):
    """Cross-sweep head-to-head tournament using stored outputs."""
    from .tournament import run_tournament as _run_t
    _run_t(
        bucket=bucket,
        category=category,
        top_n=top_n,
        mode=mode,
        parallelism=parallelism,
        tag=tag,
    )


@app.command()
def tournaments():
    """List all tournaments in the DB."""
    from .db import db as _db
    d = _db()
    if "tournaments" not in d.table_names():
        console.print("[yellow]no tournaments yet[/]")
        return
    t = Table(title="Tournaments")
    t.add_column("ID"); t.add_column("Created"); t.add_column("Mode"); t.add_column("Bucket"); t.add_column("Category"); t.add_column("Top N"); t.add_column("Tag")
    for row in d.execute("SELECT id, created_at, mode, filter_bucket, filter_category, top_n, tag FROM tournaments ORDER BY created_at DESC"):
        t.add_row(row[0], (row[1] or "")[:19], row[2] or "", row[3] or "", row[4] or "", str(row[5]), row[6] or "")
    console.print(t)


@app.command()
def show(run_id: int):
    """Dump a single run's prompt/response/scores from the DB."""
    from .db import db as _db
    d = _db()
    run = d["runs"].get(run_id)
    console.print(f"[bold cyan]run {run_id}[/] — {run['model']} on {run['task_id']} ({run['category']})")
    console.print(f"tok/s: {run['tokens_per_sec']:.1f}  ttft: {run['ttft_ms']}ms  rss: {run['peak_rss_mb']:.0f}MB")
    console.print("\n[bold]response:[/]\n" + (run['response'] or '(empty)'))
    console.print("\n[bold]scores:[/]")
    for s in d.execute("SELECT judge_model, score, reasoning FROM scores WHERE run_id=?", [run_id]):
        console.print(f"  {s[0]}: {s[1]}/5 — {s[2]}")


if __name__ == "__main__":
    app()
