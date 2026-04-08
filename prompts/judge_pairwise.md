You are comparing two AI model responses to the same task. You are blinded to which model produced which response. Pick the better response, or declare a tie if they are genuinely equivalent in quality.

**Task:**
---
{task_prompt}
---

**Response A:**
---
{response_a}
---

**Response B:**
---
{response_b}
---

Judge on: correctness first, then clarity, then concision. Ignore stylistic preference unless one response is clearly harder to use.

Return ONLY a single JSON object:

{{
  "winner": "A" | "B" | "tie",
  "reasoning": "<≤30 words>"
}}
