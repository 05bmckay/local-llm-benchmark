# Local LLM Benchmark: 23 Models on a MacBook Pro M4 Pro (24GB)

**An autonomous, Claude-judged evaluation of every local model that fits in 24GB of unified memory.**

> Hardware: MacBook Pro M4 Pro, 24GB RAM, macOS 26
> Runtime: Ollama 0.20.x + LM Studio (for Ollama-incompatible GGUFs)
> Judge: Claude Sonnet 4.6 (absolute scoring) + Claude Opus 4.6 (tiebreaks)
> Date: April 8-9, 2026

---

## TL;DR

We benchmarked 23 local LLMs across 35 tasks in 9 categories (coding, reasoning, agentic tool use, writing, PM, instruction following), then ran 4,000+ pairwise head-to-head matches judged by Claude to produce Elo rankings. Along the way we discovered a critical bug affecting how most benchmarking tools measure reasoning-capable models.

**The winners:**

| use case | model | why |
|---|---|---|
| Overall Elo champion | **devstral-small-2** (24B) | Wins head-to-head more than any other model |
| Highest raw quality | **qwen3-coder-30b** (4.40/5) | Best average score across all categories |
| Best daily driver | **gemma4-e4b** (7.5B) | 4.11-4.29 quality at 55-60 tok/s. Instant TTFT |
| Best for coding | **phi4-reasoning** (14B) | 5.00 in Elixir, 4.75 in Python, 4.50 in bash |
| Best tiny model | **qwen2.5-1.5b** (1.5B) | 164 tok/s, runs on anything, best <3B composite |

---

## Methodology

### Task suite (35 tasks, 9 categories)

| category | tasks | what it tests |
|---|---|---|
| `agentic_tools` | 10 | Tool-call JSON generation, multi-step orchestration, refusal, schema compliance (includes BFCL-style tasks) |
| `coding_python` | 4 | Algorithm implementation, data processing, debugging |
| `coding_js` | 3 | React components, async patterns, DOM manipulation |
| `coding_elixir` | 3 | Pattern matching, GenServer, pipeline composition |
| `coding_bash` | 3 | Curl/jq pipelines, find commands, safe scripting |
| `reasoning` | 4 | Logic grids, word problems, code tracing, unit conversion |
| `instruction` | 3 | Constraint following, format compliance, negative constraints |
| `writing_business` | 3 | Cold outreach, incident postmortems, executive summaries |
| `pm` | 2 | PRD writing, prioritization frameworks |

### Scoring

**Absolute scoring (1-5):** Each model response is graded independently by Claude Sonnet 4.6 against a rubric specific to each task. Score anchors: 1 = wrong/empty, 3 = partially correct, 5 = reference-quality.

**Pairwise Elo:** Top models from each bucket enter round-robin tournaments where Claude compares responses head-to-head (blinded to model identity). Results feed a Bradley-Terry model to produce Elo ratings. 4,005 total pairwise matches across 8 tournaments.

### Timing

All timing metrics use Ollama's server-reported `eval_count` and `eval_duration` (not client-side chunk counting) for accurate tok/s. TTFT is measured from request submission to first generated token. Models are cold-loaded, warmed up with a single prompt, then run all 35 tasks sequentially before being unloaded.

---

## Global Elo Rankings

*Cross-size tournament: 12 models, 2,246 pairwise matches, all 35 tasks.*

| rank | model | size | Elo | W | L | T | quality |
|---|---|---|---|---|---|---|---|
| 1 | **devstral-small-2** | 24B | **1193** | 245 | 49 | 85 | 4.34 |
| 2 | **qwen3-coder-30b** | 30B | **1155** | 230 | 68 | 81 | 4.40 |
| 3 | phi4-reasoning | 14B | 1050 | 187 | 133 | 50 | 4.38 |
| 4 | gemma4-e4b-q4ks-fast | 7.5B | 1052 | 173 | 116 | 90 | 4.29 |
| 5 | phi4-14b | 14B | 1048 | 173 | 120 | 86 | 4.06 |
| 6 | gemma3:12b-it-qat | 12B | 1021 | 158 | 135 | 86 | 3.69 |
| 7 | deepseek-r1:14b | 14B | 966 | 130 | 166 | 74 | 3.88 |
| 8 | gpt-oss-20b | 20B | 953 | 148 | 198 | 24 | 3.91 |
| 9 | gemma4-e4b | 7.5B | 911 | 117 | 213 | 49 | 4.11 |
| 10 | gemma3n | 7B | 903 | 96 | 201 | 82 | 3.52 |
| 11 | gemma4-26b | 26B | 874 | 104 | 227 | 19 | 3.66 |
| 12 | mistral-nemo-12b | 12B | 873 | 88 | 223 | 68 | 3.51 |

**Key insight:** Elo and raw quality diverge. devstral-small-2 is Elo #1 despite being only #3 in quality — it wins head-to-head matchups more *consistently* across categories, even if its average score isn't the highest. qwen3-coder-30b has the highest average quality but is less consistent in pairwise comparisons.

---

## Full Quality Leaderboard

*Average score (1-5) across 35 tasks. All models, all sweeps.*

| rank | model | bucket | quality | tok/s | TTFT | composite |
|---|---|---|---|---|---|---|
| 1 | qwen3-coder-30b | <35B | **4.40** | 41.9 | 6.5s | 36.8 |
| 2 | phi4-reasoning | <15B | **4.38** | 18.6 | 0.8s | 16.3 |
| 3 | devstral-small-2 | <25B | **4.34** | 14.5 | 1.3s | 12.6 |
| 4 | gemma4-e4b (LM Studio) | <10B | **4.29** | ~60 | 0.4s | ~51 |
| 5 | gemma4-e4b (Ollama) | <10B | **4.11** | 55.9 | 0.5s | 46.0 |
| 6 | phi4-14b | <15B | **4.06** | 24.8 | 0.7s | 20.2 |
| 7 | gpt-oss-20b | <25B | 3.91 | 52.5 | 0.5s | 41.1 |
| 8 | gemma4-26b | <35B | 3.91 | 51.0 | 0.9s | 39.8 |
| 9 | deepseek-r1:14b | <15B | 3.88 | 20.1 | 46.3s | 15.6 |
| 10 | hermes4-14b | <15B | 3.84 | 24.6 | 0.8s | 18.9 |
| 11 | gemma3:12b-it-qat | <15B | 3.69 | 25.8 | 0.9s | 19.0 |
| 12 | gemma3n | <7B | 3.52 | 46.8 | 0.7s | 33.0 |
| 13 | mistral-nemo-12b | <15B | 3.51 | 30.2 | 0.5s | 21.2 |
| 14 | qwen2.5-coder-3b | <7B | 3.44 | 94.7 | 0.3s | 65.1 |
| 15 | granite3.3:8b | <10B | 3.23 | 39.9 | 0.5s | 25.8 |
| 16 | hermes3:8b | <10B | 3.17 | 47.2 | 0.5s | 29.9 |
| 17 | llama3.2-3b | <7B | 3.12 | 100.7 | 0.3s | 62.9 |
| 18 | phi4-mini-3.8b | <7B | 3.00 | 73.5 | 0.3s | 44.1 |
| 19 | smollm3-3b | <7B | 2.85 | 97.3 | 0.3s | 55.5 |
| 20 | xLAM-2-8b | <10B | 2.83 | 47.3 | 0.4s | 26.7 |
| 21 | qwen2.5-1.5b | <3B | 2.69 | 164.8 | 0.2s | 88.5 |
| 22 | smollm2-1.7b | <3B | 2.34 | 112.0 | 0.2s | 52.5 |
| 23 | deepseek-r1-1.5b | <3B | 1.80 | 157.8 | 3.2s | 56.8 |

*Composite = (quality / 5) × tok/s. Higher is better — rewards both quality and speed.*

---

## Per-Bucket Champions

### <3B — The travel / embedded tier

| rank | model | quality | tok/s | composite |
|---|---|---|---|---|
| 1 | **qwen2.5-1.5b** | 2.69 | 164.8 | **88.5** |
| 2 | smollm2-1.7b | 2.34 | 112.0 | 52.5 |
| 3 | deepseek-r1-1.5b | 1.80 | 157.8 | 56.8 |

**Winner: qwen2.5-1.5b.** Composite champion by a mile. deepseek-r1 is fast but its 3.2s TTFT (reasoning startup cost) and 1.80 quality make it the worst value. smollm2 is simpler but honest.

### <7B — The sweet spot for speed

| rank | model | quality | tok/s | composite |
|---|---|---|---|---|
| 1 | **gemma3n** | 3.52 | 46.8 | 33.0 |
| 2 | qwen2.5-coder-3b | 3.44 | 94.7 | 65.1 |
| 3 | llama3.2-3b | 3.12 | 100.7 | 62.9 |
| 4 | phi4-mini-3.8b | 3.00 | 73.5 | 44.1 |
| 5 | smollm3-3b | 2.85 | 97.3 | 55.5 |

**Quality winner: gemma3n.** But qwen2.5-coder-3b has the best composite (65.1) — nearly 2× gemma3n's speed at only 0.08 less quality. For coding tasks specifically, qwen2.5-coder-3b is the pick.

### <10B — The daily driver tier

| rank | model | quality | Elo (bucket) | tok/s |
|---|---|---|---|---|
| 1 | **gemma4-e4b** (LM Studio) | 4.29 | 1st (91W) | ~60 |
| 2 | **gemma4-e4b** (Ollama) | 4.11 | 2nd (67W) | 55.9 |
| 3 | hermes3-8b | 3.17 | 3rd (46W) | 47.2 |
| 4 | granite3.3:8b | 3.23 | 4th (44W) | 39.9 |
| 5 | xLAM-2-8b | 2.83 | 5th (35W) | 47.3 |

**Gemma 4 E4B dominates this tier completely.** Both variants are top-2. The LM Studio Q4_K_S variant scores higher (4.29 vs 4.11) — possibly because LM Studio's newer llama.cpp handles the architecture better, or because the Q4_K_S quantization happens to preserve quality for this model's parameter distribution.

### <15B — The quality-first tier

| rank | model | quality | Elo (bucket) | tok/s |
|---|---|---|---|---|
| 1 | **phi4-reasoning** | 4.38 | 1st (94W) | 18.6 |
| 2 | phi4-14b | 4.06 | 2nd (82W) | 24.8 |
| 3 | deepseek-r1:14b | 3.88 | 4th (64W) | 20.1 |
| 4 | hermes4-14b | 3.84 | 6th (44W) | 24.6 |
| 5 | gemma3:12b-it-qat | 3.69 | 3rd (81W) | 25.8 |
| 6 | mistral-nemo-12b | 3.51 | 5th (49W) | 30.2 |

**phi4-reasoning is the clear <15B champion** in both quality and Elo. The reasoning variant beats vanilla phi4-14b by 0.32 quality points — the thinking budget pays for itself. Interesting: gemma3:12b-it-qat ranks 3rd in Elo despite 5th in quality, suggesting it wins specific matchups where its strengths align.

### <25B — Sparse but strong

| model | quality | tok/s |
|---|---|---|
| **devstral-small-2** | 4.34 | 14.5 |
| gpt-oss-20b | 3.91 | 52.5 |

**devstral-small-2 wins quality; gpt-oss-20b wins speed.** devstral's 14.5 tok/s makes it painful for interactive chat. gpt-oss is 3.6× faster with usable quality. For batch processing or agent backends: devstral. For interactive use: gpt-oss.

### <35B — The heavyweights

| model | quality | tok/s |
|---|---|---|
| **qwen3-coder-30b** | 4.40 | 41.9 |
| gemma4-26b | 3.91 | 51.0 |

**qwen3-coder-30b is the overall quality champion** across the entire benchmark. At 41.9 tok/s it's surprisingly usable for a 30B model on 24GB RAM. gemma4-26b is faster but 0.49 quality points behind.

---

## Category Champions

*Best average score per category across all models. Minimum 2 runs required.*

| category | champion | score | runner-up | score |
|---|---|---|---|---|
| **agentic_tools** | qwen3-coder-30b | 4.80 | gemma4-e4b (LMS) | 4.80 |
| **coding_bash** | phi4-reasoning | 4.50 | hermes4-14b | 4.50 |
| **coding_elixir** | qwen2.5-coder-3b | 5.00 | phi4-reasoning | 5.00 |
| **coding_js** | phi4-reasoning | 4.33 | qwen3-coder-30b | 4.00 |
| **coding_python** | qwen3-coder-30b | 4.75 | phi4-reasoning | 4.75 |
| **instruction** | gemma4-e4b variants | 5.00 | phi4-reasoning | 4.00 |
| **pm** | qwen3-coder-30b | 4.50 | gemma4-e4b | 4.50 |
| **reasoning** | phi4-14b | 5.00 | devstral-small-2 | 5.00 |
| **writing** | gemma4-e4b (LMS) | 4.33 | devstral-small-2 | 4.33 |

**phi4-reasoning and qwen3-coder-30b are the most versatile models** — appearing in the top-2 of 5+ categories each. For coding specifically, phi4-reasoning is unmatched: 5.00 in Elixir, 4.75 in Python, 4.50 in bash, 4.33 in JS.

**Surprising finding: qwen2.5-coder-3b scores a perfect 5.00 in Elixir** — matching models 5-10× its size. If you only need Elixir code generation, this 1.9GB model is as good as it gets.

---

## The Big Discovery: The "Thinking Tax"

Midway through benchmarking, we discovered a critical bug that likely affects other benchmarking setups too.

### The bug

Ollama's `/api/chat` streaming endpoint returns model output across multiple fields:

```json
{"message": {"role": "assistant", "content": "...", "thinking": "...", "tool_calls": [...]}}
```

Most client code (including ours, initially) only reads `message.content`. But several models route significant output to `thinking` (reasoning chains) or `tool_calls` (structured tool use):

| model | content chars | thinking chars | % lost |
|---|---|---|---|
| hermes4-14b | 631 | 1,910 | **75%** |
| gemma4-e4b | 933 | 1,894 | **67%** |
| gpt-oss-20b | 0 | all output | **100%** on some tasks |

### The impact

After fixing the client to capture all channels, model scores *dropped*:

| model | pre-fix | post-fix | delta |
|---|---|---|---|
| hermes4-14b | 4.48 | 3.84 | **-0.64** |
| gemma4-26b | 4.51 | 3.91 | **-0.60** |
| gemma4-e4b | 4.47 | 4.11 | **-0.36** |
| gpt-oss-20b | 4.09 | 3.91 | **-0.18** |

Why? When the judge only sees clean conclusions (the `content` field), it rates higher. When it sees the full reasoning chain — often messy, repetitive, exploratory — it penalizes verbosity and lack of conciseness. Models that don't use a thinking channel (devstral, qwen3-coder, phi4-reasoning with inline `<think>` tags) were unaffected and rose in the rankings.

### The lesson

**If you're benchmarking local models and not capturing the `thinking` field, your scores for reasoning-capable models are wrong.** They may be wrong in *either direction* — inflated (if the judge rewards conciseness) or deflated (if the model's best reasoning is hidden). Our experience was that scores dropped, but this depends entirely on your evaluation rubric.

This also affects TTFT measurement: if you wait for the first `content` token, models that think for 20 seconds before responding appear to have 20-second load times. The fix is to trigger TTFT on the first token of *any* field.

---

## What We Tried That Didn't Work

### Claude-distilled models: total bust

We pulled 5 Claude-distilled Qwen3.5 variants from HuggingFace. Results:

- **3 models failed to load** — Ollama's bundled llama.cpp doesn't support the `qwen35` architecture yet (HTTP 500 on every request)
- **1 model loaded but produced garbage** — broken chat template caused repetitive `A.\nB.\nC.\nD.\n` output with `<|endoftext|><|im_start|>` leak tokens
- **1 model needed a different backend** — the gemma4 architecture also isn't supported in Ollama's llama.cpp

~49 GB of models pulled and deleted. The concept is interesting but the model packaging ecosystem isn't ready. Revisit when Ollama ships a newer llama.cpp vendor sync.

### Ollama architecture limitations

Ollama (as of 0.20.x) bundles a llama.cpp build that predates support for two architectures:
- `gemma4` — PR #21309 in llama.cpp
- `qwen35` / `qwen35moe` — PR #19870 in llama.cpp

Models from the official Ollama registry (e.g., `gemma4:e4b`, `gemma4:26b`) work because they ship with compatible metadata. But third-party GGUFs from HuggingFace using these architectures fail with HTTP 500.

**Workaround:** LM Studio ships a more recent llama.cpp build and handles both architectures. We built an OpenAI-compatible backend adapter (`bench/openai_client.py`) that routes `lmstudio:<model>` prefixed models through LM Studio's `/v1/chat/completions` endpoint. This also works with `llama-server` and `mlx_lm.server`.

---

## Infrastructure

The benchmark system is fully autonomous and reusable:

- **35 tasks** across 9 categories, stored as YAML with rubrics and reference solutions
- **Automatic discovery** of Ollama models with size-bucket classification
- **Dual-timeout system**: separate budgets for model loading (cold start) and generation, scaled per bucket
- **TTFT-aware timing**: task clock starts after first token, not request submission
- **Parallel judging**: 6-worker ThreadPool for Claude CLI calls (~5× speedup over sequential)
- **Resume-capable sweeps**: kill and restart without losing completed runs
- **SQLite storage**: all prompts, responses, scores, and pairwise results preserved for re-analysis
- **Cross-sweep tournaments**: Bradley-Terry Elo from pairwise head-to-head on shared task sets
- **Multi-backend**: Ollama + OpenAI-compatible (LM Studio / llama-server / MLX)
- **Streamlit explorer**: interactive leaderboards, task drill-down, model comparison, run inspector

### Stats

- 23 models tested across 6 size buckets
- 806 successful generation runs
- 852 absolute judge scores
- 4,005 pairwise tournament matches across 8 tournaments
- 16 sweeps over ~12 hours of wall-clock time

---

## Daily Driver Recommendations

*For a MacBook Pro M4 Pro with 24GB RAM:*

| use case | model | why |
|---|---|---|
| **Interactive chat** | gemma4-e4b | 4.11 quality, 56 tok/s, 0.5s TTFT. Best balance of speed and smarts for daily use. |
| **Maximum quality** | qwen3-coder-30b | 4.40 quality, 42 tok/s. Highest raw score. Uses most of your RAM (18GB). |
| **Coding** | phi4-reasoning | Perfect scores in Elixir, near-perfect in Python/bash. Slow (19 tok/s) but thorough. |
| **Agentic / tool use** | qwen3-coder-30b | 4.80 agentic score, clean tool-call JSON generation. |
| **Background agent** | devstral-small-2 | Elo #1, most consistent head-to-head winner. Slow for interactive but ideal for batch. |
| **Travel / low power** | qwen2.5-1.5b | 165 tok/s, 0.2s TTFT, runs on anything. Composite champion in its weight class. |
| **Quick Elixir help** | qwen2.5-coder-3b | Perfect 5.00 in Elixir at 95 tok/s. Only 1.9GB on disk. |

---

*Built with [Claude Code](https://claude.ai/code). All model outputs and judge scores stored in SQLite for reproducibility. Source and tasks available in the `ai-benchmarks` repository.*
