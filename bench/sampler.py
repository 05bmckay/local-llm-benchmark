"""Sample peak RSS of the ollama server process during a generation."""
from __future__ import annotations

import threading
import time

import psutil


def find_ollama_procs() -> list[psutil.Process]:
    procs = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            if name == "ollama" or "ollama" in " ".join(p.info.get("cmdline") or []).lower():
                procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


class RSSSampler:
    def __init__(self, interval_s: float = 0.1):
        self.interval_s = interval_s
        self.peak_mb: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            total = 0
            for p in find_ollama_procs():
                try:
                    total += p.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            mb = total / (1024 * 1024)
            if mb > self.peak_mb:
                self.peak_mb = mb
            time.sleep(self.interval_s)

    def __enter__(self) -> "RSSSampler":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *a) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
