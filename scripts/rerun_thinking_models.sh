#!/usr/bin/env bash
# Re-run models that were affected by the dropped-thinking-channel bug
# (fix landed in bench/ollama.py + bench/openai_client.py).
#
# Models to re-run:
#   - gpt-oss-20b      (4 fully empty responses, content-only path)
#   - hermes4-14b      (chars/tok=0.60 — losing ~75% to thinking)
#   - gemma4-26b       (chars/tok=0.62 + 1 empty response)
#   - gemma4-e4b       (chars/tok normal but probe shows 67% in thinking — surprise!)
#
# Logs to results/rerun_thinking.log. Waits for the overnight sweep to fully
# release Ollama before starting so the two don't fight for VRAM.

set -u
cd "$(dirname "$0")/.."
LOG=results/rerun_thinking.log
exec >>"$LOG" 2>&1

say() { echo; echo "=== $(date '+%H:%M:%S') $* ==="; }

say "WAIT for overnight script (PID 29783) to exit"
while kill -0 29783 2>/dev/null; do
    sleep 30
done
echo "  overnight script gone"

# Extra grace period in case Ollama is still unloading
sleep 10

say "DELETE old broken rows for the 4 affected models (so re-run is clean)"
.venv/bin/python <<'PY'
from bench.db import db
d = db()
TARGETS = ["gpt-oss-20b", "hermes4-14b", "gemma4-26b", "gemma4-e4b"]
for model in TARGETS:
    n_runs = d.execute("SELECT COUNT(*) FROM runs WHERE model=?", [model]).fetchone()[0]
    if n_runs == 0:
        print(f"  {model}: 0 rows (skip)")
        continue
    d.execute("DELETE FROM scores WHERE run_id IN (SELECT id FROM runs WHERE model=?)", [model])
    d.execute("DELETE FROM pairwise WHERE model_a=? OR model_b=?", [model, model])
    d.execute("DELETE FROM tournament_matches WHERE model_a=? OR model_b=?", [model, model])
    d.execute("DELETE FROM runs WHERE model=?", [model])
    d.conn.commit()
    print(f"  {model}: deleted {n_runs} runs")
PY

say "BENCH gemma4-e4b (rerun)"
.venv/bin/bench run --models "gemma4-e4b" || echo "  failed"

say "BENCH gpt-oss-20b (rerun)"
.venv/bin/bench run --models "gpt-oss-20b" || echo "  failed"

say "BENCH hermes4-14b (rerun)"
.venv/bin/bench run --models "hermes4-14b" || echo "  failed"

say "BENCH gemma4-26b (rerun)"
.venv/bin/bench run --models "gemma4-26b" || echo "  failed"

say "TOURNAMENT <10B (refresh — gemma4-e4b changed)"
.venv/bin/bench tournament --bucket "<10B" --top-n 6 || true

say "TOURNAMENT <15B (refresh — hermes4-14b changed)"
.venv/bin/bench tournament --bucket "<15B" --top-n 6 || true

say "TOURNAMENT <25B (refresh — gpt-oss-20b changed)"
.venv/bin/bench tournament --bucket "<25B" --top-n 6 || true

say "TOURNAMENT <35B (refresh — gemma4-26b changed)"
.venv/bin/bench tournament --bucket "<35B" --top-n 6 || true

say "TOURNAMENT GLOBAL refresh"
.venv/bin/bench tournament --top-n 12 || true

say "DONE — all 4 models re-run with thinking-capture fix"
