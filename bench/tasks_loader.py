"""Load Task YAMLs from tasks/."""
from __future__ import annotations

from pathlib import Path

import yaml

from .schema import Task

TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"


def load_all(category: str | None = None) -> list[Task]:
    out: list[Task] = []
    root = TASKS_DIR if category is None else TASKS_DIR / category
    for p in sorted(root.rglob("*.yaml")):
        data = yaml.safe_load(p.read_text())
        out.append(Task.model_validate(data))
    return out
