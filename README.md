# ai-benchmarks

Local Ollama model bench with Claude-as-judge. Runs models × tasks, measures quality (rubric-graded), throughput, latency, and RAM; ranks fairly within size buckets (`<1B`, `<3B`, `<7B`, `<10B`, `<15B`, `<25B`, `<35B`).

## Setup

```bash
cd ~/ai-benchmarks
uv sync
```

Requires: Ollama running on `localhost:11434`, `claude` CLI authed.

## Usage

```bash
bench models                      # list discovered models + buckets
bench tasks                       # list tasks
bench run --smoke                 # 1 task/category × all models (fast)
bench run                         # full sweep
bench run --models qwen3-coder:30b,devstral-small-2:latest
bench run --category coding_elixir
bench report                      # regenerate latest report
```

Results land in `results/bench.sqlite` and markdown reports in `results/reports/`.

## Judging

- **Absolute**: Sonnet 4.6 scores each response 1–5 against a weighted rubric.
- **Pairwise**: Top quartile per category get round-robin head-to-head, fit via Bradley-Terry → Elo.
- Tiebreaks escalate to Opus 4.6.

Judging uses your local `claude` CLI — no extra API key.

## Adding tasks

Drop a YAML in `tasks/<category>/`. Schema in `bench/schema.py::Task`.

## Voice-match writing

Drop samples in `fixtures/voice/` — see README there.
