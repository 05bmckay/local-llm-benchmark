#!/usr/bin/env bash
# Overnight: wait for REAP Qwen3.5-28B download, convert to GGUF Q4_K_M,
# load in LM Studio, bench it.
set -u
cd "$(dirname "$0")/.."
LOG=results/reap_qwen.log
mkdir -p results models
exec >>"$LOG" 2>&1

say() { echo; echo "=== $(date '+%H:%M:%S') $* ==="; }

MODEL_DIR="models/qwen35-28b-reap"
GGUF_F16="models/qwen35-28b-reap-f16.gguf"
GGUF_Q4="models/qwen35-28b-reap-q4km.gguf"

say "WAIT for HF download to finish"
# Wait until safetensors files appear and no huggingface-cli is running
while true; do
    if ! pgrep -f "huggingface-cli.*Qwen-3.5-28B" >/dev/null 2>&1; then
        echo "  huggingface-cli process gone"
        break
    fi
    SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    echo "  $(date '+%H:%M:%S') downloading... $SIZE"
    sleep 60
done

# Verify download
SAFETENSORS=$(ls "$MODEL_DIR"/*.safetensors 2>/dev/null | wc -l | tr -d ' ')
if [ "$SAFETENSORS" -eq 0 ]; then
    say "ERROR: no safetensors found in $MODEL_DIR — download may have failed"
    exit 1
fi
say "Download complete — $SAFETENSORS safetensors files"

say "CONVERT safetensors → GGUF (f16)"
convert_hf_to_gguf.py "$MODEL_DIR" --outfile "$GGUF_F16" --outtype f16
if [ ! -f "$GGUF_F16" ]; then
    say "ERROR: convert_hf_to_gguf.py failed"
    exit 1
fi
echo "  f16 GGUF size: $(du -sh "$GGUF_F16" | cut -f1)"

say "QUANTIZE f16 → Q4_K_M"
llama-quantize "$GGUF_F16" "$GGUF_Q4" Q4_K_M
if [ ! -f "$GGUF_Q4" ]; then
    say "ERROR: llama-quantize failed"
    exit 1
fi
echo "  Q4_K_M size: $(du -sh "$GGUF_Q4" | cut -f1)"

say "CLEANUP f16 GGUF (keep only Q4)"
rm -f "$GGUF_F16"

say "LOAD in LM Studio"
lms server start 2>/dev/null || true
# Import the GGUF into LM Studio
lms import "$GGUF_Q4" -y 2>&1 || true
sleep 5
# Find the model identifier
IDENT=$(lms ls 2>&1 | grep -i "qwen.*reap" | awk '{print $1}' | head -1)
if [ -z "$IDENT" ]; then
    # Fallback: try loading by path
    IDENT="qwen35-28b-reap-q4km"
    lms load "$GGUF_Q4" -y 2>&1
else
    lms load "$IDENT" -y 2>&1
fi
echo "  loaded as: $IDENT"
sleep 10

say "SMOKE TEST"
.venv/bin/python -c "
from bench import openai_client
r = openai_client.generate('$IDENT', 'What is 27 * 14?', timeout_s=60, load_budget_s=120)
print('error:', r.error)
print('tokens:', r.tokens_out, 'tps:', round(r.tokens_per_sec, 1))
print('text:', r.text[:200])
"

say "BENCH"
.venv/bin/bench run --models "lmstudio:$IDENT" || echo "  bench failed"

say "GENERATE BENCH RESULTS FOR MODEL CARD"
RESULTS=$(.venv/bin/python <<'PY'
from bench.db import db
d = db()
# Find the REAP qwen model
models = [r[0] for r in d.execute("SELECT DISTINCT model FROM runs WHERE model LIKE '%qwen%reap%' OR model LIKE '%qwen35-28b%'")]
if not models:
    print("NO RESULTS FOUND")
    exit(1)
m = models[0]
overall = list(d.execute("SELECT AVG(s.score), AVG(r.tokens_per_sec), AVG(r.ttft_ms), COUNT(*), SUM(CASE WHEN r.error IS NOT NULL AND r.error!='' THEN 1 ELSE 0 END) FROM runs r JOIN scores s ON s.run_id=r.id WHERE r.model=?", [m]))[0]
print(f"model: {m}")
print(f"quality: {overall[0]:.2f}")
print(f"tps: {overall[1]:.1f}")
print(f"ttft: {overall[2]:.0f}ms")
print(f"runs: {overall[3]}")
print(f"errors: {overall[4]}")
print()
print("| category | score |")
print("|---|---|")
for r in d.execute("SELECT r.category, AVG(s.score) FROM runs r JOIN scores s ON s.run_id=r.id WHERE r.model=? GROUP BY r.category ORDER BY 2 DESC", [m]):
    print(f"| {r[0]} | {r[1]:.2f} |")
PY
)
echo "$RESULTS"

say "PUBLISH Q4_K_M TO HUGGINGFACE"
# Create model card
cat > /tmp/reap-qwen-readme.md <<CARD
---
license: apache-2.0
base_model: 0xSero/Qwen-3.5-28B-A3B-REAP
tags:
  - gguf
  - reap
  - qwen3.5
  - moe
  - quantized
---

# Qwen3.5-28B-A3B-REAP — GGUF Q4_K_M

GGUF quantization of [0xSero/Qwen-3.5-28B-A3B-REAP](https://huggingface.co/0xSero/Qwen-3.5-28B-A3B-REAP), a 20% REAP-pruned version of Qwen3.5-35B-A3B.

**REAP** (Router-weighted Expert Activation Pruning) removes the least-important MoE experts using router gate-values and activation norms. This model retains 205 of 256 experts (~80%) while keeping the same 3B active parameters per token.

## Benchmark Results

Tested on MacBook Pro M4 Pro (24GB) using our [local-llm-benchmark](https://github.com/05bmckay/local-llm-benchmark) suite — 35 tasks across 9 categories, judged by Claude Sonnet 4.6.

\`\`\`
$RESULTS
\`\`\`

## Quantization Details

| Property | Value |
|---|---|
| Original model | [0xSero/Qwen-3.5-28B-A3B-REAP](https://huggingface.co/0xSero/Qwen-3.5-28B-A3B-REAP) |
| Base model | [Qwen/Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) |
| Quantization | Q4_K_M |
| Pruning method | REAP (20% expert removal) |
| Experts | 205 / 256 (80% retained) |
| Active params/token | 3B |
| Conversion tool | llama.cpp convert_hf_to_gguf.py + llama-quantize |

## Usage

### LM Studio
\`\`\`bash
lms get "https://huggingface.co/05bmckay/Qwen3.5-28B-A3B-REAP-GGUF" -y --gguf
lms load <model-id> -y
# OpenAI-compatible API at localhost:1234
\`\`\`

### llama.cpp
\`\`\`bash
llama-server -m qwen35-28b-reap-q4km.gguf --port 8080 -ngl 99
\`\`\`

## Credits

- **REAP method & pruned weights**: [0xSero](https://huggingface.co/0xSero) — [REAP paper (ICLR 2026)](https://arxiv.org/abs/2510.13999)
- **Base model**: [Qwen Team, Alibaba Cloud](https://huggingface.co/Qwen)
- **Quantization & benchmarking**: [05bmckay](https://github.com/05bmckay/local-llm-benchmark)
CARD

# Create repo and upload
huggingface-cli repo create Qwen3.5-28B-A3B-REAP-GGUF --type model -y 2>&1 || true
huggingface-cli upload 05bmckay/Qwen3.5-28B-A3B-REAP-GGUF "$GGUF_Q4" --repo-type model 2>&1
huggingface-cli upload 05bmckay/Qwen3.5-28B-A3B-REAP-GGUF /tmp/reap-qwen-readme.md README.md --repo-type model 2>&1

say "DONE — published to https://huggingface.co/05bmckay/Qwen3.5-28B-A3B-REAP-GGUF"
echo "Check results with:"
echo "  tail -100 results/reap_qwen.log"
