You are grading a local AI model's response to a benchmark task. You are a strict but fair judge.

**Task ID:** {task_id}
**Category:** {category}

**Task prompt:**
---
{task_prompt}
---

**Rubric (weighted criteria):**
{rubric}

**Reference / ideal solution (if any):**
---
{reference}
---

**Model response to grade:**
---
{response}
---

Score the response against the rubric. Be specific about which criteria passed/failed.
Return ONLY a single JSON object (no prose, no code fences) with this exact shape:

{{
  "score": <integer 1-5, where 1=unusable, 3=partially correct, 5=excellent>,
  "criteria": [
    {{"name": "<short name>", "pass": <true|false>, "note": "<≤15 words>"}}
  ],
  "reasoning": "<≤40 words overall>"
}}

Rules:
- Score 1 if the response is empty, off-topic, or fundamentally wrong.
- Score 5 only if the response meets or exceeds all weighted criteria.
- Weight the overall score by the rubric weights.
- Do not penalize verbosity unless the rubric explicitly says to.
- Do not reward content that wasn't asked for.
