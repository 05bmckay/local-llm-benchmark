"""Sample peak RSS of the ollama server process during a generation."""
from __future__ import annotations

import threading
import time

import psutil


def find_ollama_procs() -> list[psutil.Process]:
    """Find ollama processes by name only.

    Deliberately does NOT inspect cmdline — on macOS 14+ `sysctl(KERN_PROCARGS2)`
    is restricted for non-owned processes and raises PermissionError/SystemError
    which escapes psutil's normal exception contract and kills the caller thread.
    Name matching is sufficient for ollama ("ollama" binary + "Ollama Helper").
    """
    procs = []
    try:
        iterator = psutil.process_iter(["name"])
    except Exception:
        return procs
    for p in iterator:
        try:
            name = (p.info.get("name") or "").lower()
            if "ollama" in name:
                procs.append(p)
        except Exception:
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
            try:
                total = 0
                for p in find_ollama_procs():
                    try:
                        total += p.memory_info().rss
                    except Exception:
                        continue
                mb = total / (1024 * 1024)
                if mb > self.peak_mb:
                    self.peak_mb = mb
            except Exception:
                # never let this thread die — RSS sampling is best-effort
                pass
            time.sleep(self.interval_s)

    def __enter__(self) -> "RSSSampler":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *a) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
