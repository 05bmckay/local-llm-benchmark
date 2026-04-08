from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import runner
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
        t.add_row(m.name, f"{m.params_b:.1f}B", m.bucket, m.quant, f"{m.approx_ram_gb:.1f}")
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
):
    """Run a sweep."""
    model_filter = [m.strip() for m in models.split(",")] if models else None
    sid = runner.run_sweep(
        model_filter=model_filter,
        category_filter=category,
        smoke=smoke,
        do_pairwise=not no_pairwise,
    )
    path = gen_report(sid)
    console.print(f"[green]report:[/] {path}")


@app.command()
def report(sweep_id: str = typer.Option(None)):
    """Regenerate report for a sweep (default: latest)."""
    path = gen_report(sweep_id)
    console.print(f"[green]report:[/] {path}")


if __name__ == "__main__":
    app()
