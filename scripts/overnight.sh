#!/usr/bin/env bash
# Overnight automation: wait for in-flight sweep, finish renames, run remaining
# benches, run tournaments. Logs everything to results/overnight.log.
set -u
cd "$(dirname "$0")/.."
LOG=results/overnight.log
mkdir -p results
exec >>"$LOG" 2>&1

say() { echo; echo "=== $(date '+%H:%M:%S') $* ==="; }

ACTIVE_SWEEP="20260408-231607-961d"

say "WAIT for sweep $ACTIVE_SWEEP to finish (poll 30s)"
while true; do
    state=$(.venv/bin/python -c "
from bench.db import db
d=db()
r=list(d.execute(\"SELECT finished_at FROM sweeps WHERE id='$ACTIVE_SWEEP'\"))
print(r[0][0] if r and r[0][0] else 'PENDING')
")
    if [ "$state" != "PENDING" ]; then
        echo "  sweep finished at $state"
        break
    fi
    sleep 30
done

say "RENAME the 3 deferred Wave 3a models"
.venv/bin/python <<'PY'
import subprocess
from bench.db import db
RENAMES = [
    ("gpt-oss:20b", "gpt-oss-20b"),
    ("devstral-small-2:latest", "devstral-small-2"),
    ("gemma4:26b", "gemma4-26b"),
]
d = db()
for old, new in RENAMES:
    cp = subprocess.run(["ollama", "cp", old, new], capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"  SKIP {old}: {cp.stderr.strip()}")
        continue
    subprocess.run(["ollama", "rm", old], capture_output=True, text=True)
    d.execute("UPDATE runs SET model=? WHERE model=?", [new, old])
    d.execute("UPDATE pairwise SET model_a=? WHERE model_a=?", [new, old])
    d.execute("UPDATE pairwise SET model_b=? WHERE model_b=?", [new, old])
    d.execute("UPDATE tournament_matches SET model_a=? WHERE model_a=?", [new, old])
    d.execute("UPDATE tournament_matches SET model_b=? WHERE model_b=?", [new, old])
    d.conn.commit()
    print(f"  renamed {old} -> {new}")
PY

say "BENCH mistral-nemo-12b"
.venv/bin/bench run --models "mistral-nemo-12b" || echo "  mistral-nemo bench failed"

say "BENCH qwen3-coder-30b (may fail if arch unsupported)"
.venv/bin/bench run --models "qwen3-coder-30b" || echo "  qwen3-coder-30b bench failed"

say "TOURNAMENT <10B + <15B already run earlier — skipping"

say "TOURNAMENT <25B"
.venv/bin/bench tournament --bucket "<25B" --top-n 6 || true

say "TOURNAMENT <35B"
.venv/bin/bench tournament --bucket "<35B" --top-n 6 || true

say "TOURNAMENT GLOBAL (true cross-size Elo, top 12 by quality)"
.venv/bin/bench tournament --top-n 12 || true

say "APPEND log entry"
.venv/bin/python <<'PY'
import datetime as dt
from bench.db import db
d = db()
out = ["", "---", "", f"## {dt.date.today().isoformat()} — Overnight run", ""]
out.append("**Renamed (cleanup pass 2):** gpt-oss-20b, devstral-small-2, gemma4-26b")
out.append("")
out.append("**New benches:**")
for sid in d.execute("SELECT id FROM sweeps WHERE finished_at >= ? ORDER BY started_at", [dt.datetime.now().replace(hour=0, minute=0, second=0).isoformat()]):
    sid = sid[0]
    rows = list(d.execute("SELECT r.model, AVG(s.score), AVG(r.tokens_per_sec), SUM(CASE WHEN r.error IS NOT NULL AND r.error!='' THEN 1 ELSE 0 END), COUNT(*) FROM runs r LEFT JOIN scores s ON s.run_id=r.id WHERE r.sweep_id=? GROUP BY r.model", [sid]))
    for m, q, tps, err, n in rows:
        q_s = f"{q:.2f}" if q else "—"
        tps_s = f"{tps:.1f}" if tps else "—"
        out.append(f"- `{m}` — score={q_s} tps={tps_s} errors={err}/{n} (sweep {sid})")
out.append("")
out.append("**Tournaments run:** `<10B`, `<15B`, `<25B`, `<35B` (see DB for details)")
out.append("")
with open("results/LOG.md", "a") as f:
    f.write("\n".join(out) + "\n")
print("  log appended")
PY

say "DONE"
