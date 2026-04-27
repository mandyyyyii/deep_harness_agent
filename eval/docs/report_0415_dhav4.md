# Report: DHAv4 (LLM Curator+Validator) on Terminal-Bench 2.0 & SWE-bench Verified

**Date:** 2026-04-15
**Model:** qwen3.5-35b-a3b, port 8051
**Sampling:** temperature=0.6, top_p=0.95, top_k=20, enable_thinking=true
**Prompts:** Revised curator (per-turn KEEP/SUMMARIZE/DROP) + revised validator (wasteful/destructive/premature checks)

---

## 1. Aggregate Results

### DHAv4 + Terminus2 on Terminal-Bench 2.0 (50 tasks, k=1)

| Metric | Value |
|---|---|
| Tasks completed | 49/50 (1 setup timeout) |
| **Passed** | **13/49 = 26.5%** |
| Agent timeouts | 27 (55%) |
| Generator tokens | 7,814,111 |
| Harness tokens | 11,290,746 |
| **Overhead** | **144.5%** |

### Mini-SWE-Configured on SWE-bench Verified (50 tasks, k=1)

| Metric | Value |
|---|---|
| Tasks completed | 50/50 |
| **Resolved** | **25/50 = 50.0%** |
| Runtime errors | 6 |
| Setup timeouts | 6 |
| Agent timeouts | 3 |

---

## 2. DHAv4 Harness Analysis

### Curator (1,693 LLM calls)

| Metric | Value |
|---|---|
| Total calls | 1,693 |
| Fallbacks (parse error) | 13 (0.8%) |
| Fallback rate | **0.8%** (well under 20% target) |

The curator makes a real LLM call every turn starting from turn 1. With the revised prompt, it manages per-turn history decisions (KEEP/SUMMARIZE/DROP) and curates the last observation. The 0.8% fallback rate shows the model reliably produces valid JSON with the new prompt format.

### Validator (1,396 LLM calls)

| Metric | Value |
|---|---|
| Total calls | 1,396 |
| Rejects | 445 |
| Fallbacks | 12 (0.9%) |
| **Reject rate** | **32.2%** |

The validator rejected 32.2% of proposed commands. This is within the <50% target but notably high. The revised prompt adds checks for destructive commands and premature submissions beyond just duplicates.

### Overhead Problem

**The harness used 144.5% of the generator's tokens** — the curator+validator together consumed more tokens than the generator itself. This is because:

1. **Curator runs every turn:** 1,693 calls across 49 tasks ≈ 34.5 calls/task. Each call sends the structured history + task + last observation to the LLM.
2. **Validator runs every turn too:** 1,396 calls ≈ 28.5 calls/task. Each call sends recent history + proposed commands.
3. Both use the same model (qwen3.5) which produces verbose thinking tokens.

The combined effect: for every 1 token the generator uses, 1.4 tokens go to the harness. The harness is more expensive than the generator it's supervising.

---

## 3. Comparison vs Baseline

### Terminal-Bench (overlapping 49 tasks)

| | Baseline (terminus-2, pass@5) | DHAv4 (terminus-2, pass@1) |
|---|---|---|
| Pass rate | **21/49 = 42.9%** | 13/49 = 26.5% |

**DHAv4 underperforms the baseline.** Even comparing pass@1 vs pass@5 (unfair to DHAv4), the gap is large. There are zero new wins — every task DHAv4 passed, the baseline also passed. There are 8 regressions (tasks the baseline solved but DHAv4 did not).

### Regressions (baseline solved, DHAv4 failed)

| Task | Likely cause |
|---|---|
| compile-compcert | Timeout (long compilation) |
| crack-7z-hash | Timeout |
| git-multibranch | Timeout |
| kv-store-grpc | Timeout |
| largest-eigenval | Timeout |
| merge-diff-arc-agi-task | Timeout |
| modernize-scientific-stack | Timeout |
| pytorch-model-cli | Timeout |

All 8 regressions are timeouts. The DHAv4 harness adds significant latency per turn (2 extra LLM calls — curator + validator), which causes tasks that barely fit within the time budget to timeout.

### SWE-bench Verified (50 tasks)

| | Full baseline (mini-swe, 494 tasks) | DHAv4 run (mini-swe, 50 tasks) |
|---|---|---|
| Resolve rate | 298/494 = 60.3% | 25/50 = 50.0% |

The 50-task sample resolved at 50%, lower than the full-run 60.3%. This is expected variance on a small sample — the first 50 tasks in swebench-verified may be harder or easier than average.

---

## 4. Diagnosis: Why DHAv4 Hurts More Than It Helps

### Root cause: overhead-induced timeouts

27 of 49 terminal-bench tasks (55%) hit AgentTimeoutError. The baseline on the same tasks had far fewer timeouts. The extra ~2 seconds per turn for curator + validator LLM calls compound across 30-50 turns into 60-100 seconds of harness overhead, pushing borderline tasks over the wall-clock limit.

### The overhead math

For a task with 40 turns:
- Generator: 40 LLM calls
- Curator: 40 LLM calls (one per turn)
- Validator: ~35 LLM calls (a few pre-filtered)
- **Total LLM calls: 115** (vs 40 without harness = 2.9x multiplier)

Each LLM call takes 2-10 seconds depending on prompt size. The harness adds 70-350 seconds of wall-clock time per task. With a 900-second timeout, this cuts the generator's effective time budget by 8-39%.

### The reject rate problem

32.2% reject rate means roughly 1 in 3 generator turns gets rejected and must be retried. Each rejection costs:
1. The rejected turn's generator tokens (wasted)
2. The validator's LLM call tokens
3. An extra generator turn to produce the replacement
4. An extra validator call on the replacement

A 32% reject rate effectively adds ~50% more turns to each task, further compounding the timeout problem.

### Value delivered

On the positive side, the curator was working as designed (0.8% fallback rate, actively summarizing old history turns). But the token savings from history compression are overwhelmed by the harness's own token consumption (144.5% overhead).

---

## 5. Recommendations

### For iteration improvement

1. **Reduce harness call frequency.** Don't call curator and validator every turn. Call curator every 5th turn (history doesn't change meaningfully every turn). Call validator only when the command looks suspicious (reintroduce lightweight rule-based pre-filter for obvious PASS cases).

2. **Use a smaller/faster model for harness.** The harness doesn't need qwen3.5's full reasoning — a smaller model (or even the same model with thinking disabled and lower max_tokens) would produce adequate KEEP/SUMMARIZE/DROP decisions much faster.

3. **Reduce validator reject rate.** 32.2% is too aggressive. Tighten the REJECT criteria further — only reject when there's overwhelming evidence, not "specific evidence." The cost of a false reject (wasted turn + retry) exceeds the cost of executing a slightly wasteful command.

4. **Don't add wall-clock cost.** The fundamental problem is that harness LLM calls eat into the agent's time budget. A harness that makes the agent slower can't help even if its decisions are perfect.

### For architecture

The current DHAv4 design (synchronous LLM curator + LLM validator in the agent loop) is structurally flawed for time-budgeted benchmarks. The harness cost scales linearly with turns, and the time budget is fixed. Better approaches:

- **Async background curator** that compresses history between turns without blocking the agent
- **Rule-based validator** (as in iter01) with LLM only for genuinely ambiguous cases
- **Post-hoc analysis** rather than real-time intervention — analyze trajectories after the run and improve prompts/templates
