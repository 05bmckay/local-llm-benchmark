"""Bradley-Terry ranking from pairwise verdicts."""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def bradley_terry(pairs: list[tuple[str, str, str]], iters: int = 200) -> dict[str, float]:
    """pairs: list of (model_a, model_b, winner) where winner in {"A","B","tie"}.

    Returns per-model strength scores (sum to len(models)).
    """
    models = sorted({m for a, b, _ in pairs for m in (a, b)})
    idx = {m: i for i, m in enumerate(models)}
    n = len(models)
    if n == 0:
        return {}
    wins = np.zeros((n, n))
    for a, b, w in pairs:
        ia, ib = idx[a], idx[b]
        if w == "A":
            wins[ia, ib] += 1
        elif w == "B":
            wins[ib, ia] += 1
        else:
            wins[ia, ib] += 0.5
            wins[ib, ia] += 0.5
    p = np.ones(n)
    for _ in range(iters):
        new = np.zeros(n)
        for i in range(n):
            num = 0.0
            den = 0.0
            for j in range(n):
                if i == j:
                    continue
                total = wins[i, j] + wins[j, i]
                if total == 0:
                    continue
                num += wins[i, j]
                den += total / (p[i] + p[j])
            new[i] = num / den if den > 0 else p[i]
        if new.sum() > 0:
            new *= n / new.sum()
        p = new
    return {m: float(p[idx[m]]) for m in models}


def to_elo(strengths: dict[str, float], base: float = 1000.0, scale: float = 400.0) -> dict[str, float]:
    if not strengths:
        return {}
    import math
    vals = {m: math.log(max(s, 1e-6)) for m, s in strengths.items()}
    mean = sum(vals.values()) / len(vals)
    return {m: base + scale * (v - mean) / math.log(10) for m, v in vals.items()}
