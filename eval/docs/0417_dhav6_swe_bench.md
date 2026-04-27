# DHAv6+MiniSwe vs MiniSwe Baseline on SWE-bench Verified

**Date:** 2026-04-17
**Model:** qwen3.5-35b-a3b
**Benchmark:** SWE-bench Verified (500 tasks)
**Baseline:** MiniSweConfigured (bare mini-swe-agent, no harness), results/swe_0412 + swe_0412_remaining
**Experiment:** DHAv6+MiniSweAdapter (curator + rule validator + L2), results/dhav6_swe_0416

**Status:** DHAv6 run is partial — 55/500 tasks completed (still running
or stalled). Analysis based on available data.

---

## 1. Headline Numbers

| Metric | MiniSwe Baseline | DHAv6+MiniSwe |
|--------|-----------------|---------------|
| Tasks completed | 499 | 55 (partial) |
| Pass rate | 299/499 (59.9%) | 25/55 (45.5%) |
| **Pass rate (55 overlapping tasks)** | **35/55 (63.6%)** | **25/55 (45.5%)** |
| Timeouts | 6/55 (overlap) | 20/55 (36.4%) |

DHAv6 is **18 points below baseline** on the overlapping 55 tasks.
The regression is severe.

### Task-level comparison (55 tasks)

| Category | Count | Detail |
|----------|-------|--------|
| Both pass | 22 | Core solved set |
| DHAv6 only (gains) | 3 | django-12965, django-11790, matplotlib-24149 |
| Baseline only (regressions) | 13 | See below |
| Both fail | 17 | |

DHAv6 gains 3 new solves but loses 13. **Net: −10 tasks.**

---

## 2. Token Efficiency

| Metric | Baseline | DHAv6 | Ratio |
|--------|---------|-------|-------|
| Mean per-task input tokens | 7,686K | 770K | **0.10x** |
| Total input tokens (55 tasks) | 422.7M | 42.4M | **0.10x** |
| Mean turns | 114.4 | 75.7 | 0.66x |
| Per-turn input tokens | 67.2K | 10.2K | **0.15x** |

Token efficiency is dramatic: **10x reduction** in total input tokens.
Per-turn tokens drop from 67K (baseline, growing linearly) to 10K
(DHAv6, roughly flat). This confirms the curator's compression works.

---

## 3. Harness Overhead

| Component | Mean tokens | Notes |
|-----------|-------------|-------|
| Generator | variable | agent LLM calls |
| Curator | 1.34x generator | mean summarize=835/task, mean pass=117/task |
| Validator (L2) | 28.3M total | 2,314 calls, 0 effective rejects |
| **Overhead ratio** | **2.29x** | median across 55 tasks |

The overhead ratio is **2.29x** — significantly higher than the 1.48x
on terminal-bench. Two factors:

1. **Curator overhead scales with turns.** SWE-bench tasks average 76
   turns (vs 30 on terminal-bench). More turns = more curator calls =
   more overhead.

2. **L2 validator is burning tokens for nothing.** 2,314 L2 calls
   consuming 28.3M tokens but producing **zero effective rejects**
   (0 rejects, 2 passes, 1,155 fallbacks). The L2 is running but its
   response parsing fails 99.8% of the time → falls back to PASS.
   **This is 28.3M tokens of pure waste.**

---

## 4. L2 Validator Failure

| Metric | Value |
|--------|-------|
| L2 calls | 2,314 |
| L2 tokens consumed | 28,257K |
| L2 rejects | 0 |
| L2 passes | 2 |
| L2 fallbacks (parse failure) | 1,155 |
| L2 skipped (exploration) | 2,593 |
| **Effective reject rate** | **0%** |

The L2 validator is enabled but non-functional. 1,155 of 1,157 L2
calls fall back to PASS without producing any output. L2 consumed
28.3M tokens and produced **zero effective rejects**.

**Root cause: `max_tokens=500` is too low for thinking models.**

qwen3.5-35b-a3b has chain-of-thought/thinking enabled. When the L2
prompt is sent, the model first generates internal reasoning in the
`reasoning_content` field (~2000 tokens), then generates the actual
JSON response in the `content` field (~600 tokens). Both count
against the `max_tokens` budget.

With `max_tokens=500`, the thinking alone exhausts the entire token
budget. The model never gets to write the JSON response:

```
max_tokens=500:
  reasoning_content: 500 tokens (truncated)  ← uses entire budget
  content: null                               ← never generated
  finish_reason: length

max_tokens=4096:
  reasoning_content: ~2000 tokens             ← thinking completes
  content: ~600 tokens (valid JSON)           ← response generated
  finish_reason: stop
```

The `_parse_json` function receives `None`, returns `None`, and the
fallback path increments `n_validator_l2_fallbacks`. This happens on
every single L2 call.

Confirmed by replay: with `max_tokens=4096`, the same model produces
valid JSON with correct REJECT/PASS decisions and all required fields
populated.

**Fix:** Change `validator.task_understanding.max_tokens` default
from 500 to 4096. This is the entire fix — the model, prompt, and
parsing all work correctly once the thinking budget is sufficient.

**Secondary issue:** The 2 L2 "passes" in the stats were likely
calls where the model's thinking happened to be very short (simple
commands), allowing a few content tokens to be generated.

---

## 5. Regression Analysis

### 5.1 Timeout regressions (9 of 13)

| Task | DHAv6 turns | DHAv6 input | Overhead | Curator summarizes | Rule rejects |
|------|------------|-------------|----------|-------------------|-------------|
| sympy-16792 | 133 | 2092K | 2.38x | 2581 | 4 |
| pytest-10081 | 121 | 1123K | 2.22x | 1114 | 2 |
| scikit-learn-12682 | 122 | 2076K | 1.88x | 2570 | 4 |
| pytest-7432 | 149 | 1755K | 2.49x | 1010 | 8 |
| xarray-7393 | 124 | 1318K | 2.34x | 1582 | 1 |
| django-13028 | 115 | 985K | 2.29x | 1357 | 6 |
| sympy-18211 | 124 | 1109K | 4.86x | 3191 | 16 |
| astropy-14096 | 62 | 490K | 2.13x | 590 | 9 |
| matplotlib-20488 | 25 | 80K | 3.36x | 57 | 0 |

All 9 timed out. The baseline solved these (no timeout). The
pattern: DHAv6's overhead (curator + broken L2) consumes wall-clock
time that the baseline spends on productive turns. The 2-5x overhead
ratio means each turn takes 2-5x longer, so the agent runs fewer
productive turns within the 3000s timeout.

**sympy-18211** is the worst case: 4.86x overhead, 3191 summarize
decisions. The curator is being called 124 times on a conversation
that keeps growing, and each call processes a longer history.

### 5.2 Wrong-answer regressions (4 of 13)

| Task | DHAv6 turns | DHAv6 input | Overhead |
|------|------------|-------------|----------|
| sympy-16450 | 82 | 510K | 2.78x |
| django-11333 | 60 | 514K | 1.58x |
| xarray-6461 | 52 | 302K | 3.32x |
| django-12262 | 66 | 584K | 1.64x |

These completed but produced wrong patches. The agent ran enough
turns but the fix was incorrect. Possible causes:
- Curator summarization lost critical context needed for the fix
- Higher overhead consumed time that could have been spent on
  additional debugging turns
- L2 validator (if working) might have caught shallow patches

---

## 6. What Worked

### 6.1 Three genuine gains

- **django-12965** (120 turns, 1378K) — baseline failed, DHAv6 passed.
  The curator's hints or context compression may have helped the agent
  focus on the right approach.
- **django-11790** (65 turns, 758K) — similarly.
- **matplotlib-24149** (30 turns, 96K) — quick solve; low overhead.

### 6.2 Token efficiency is massive

10x total token reduction, 6.5x per-turn reduction. On the tasks DHAv6
does solve, it uses far less compute. If the overhead problem is fixed,
this efficiency could translate to more tasks solved within the timeout.

### 6.3 Rule validator catches waste

195 rule rejects across 55 tasks (mean 3.5/task). Lower than
terminal-bench (9.1/task) because SWE-bench agents are less prone to
exact duplicate loops.

---

## 7. Root Causes of Regression

### 7.1 L2 validator is pure overhead (28.3M tokens wasted)

L2 consumes 28.3M tokens across 55 tasks and produces zero useful
rejects. This adds ~500K tokens/task of overhead and significant
latency. If L2 were disabled, the overhead ratio would drop from
~2.3x to ~1.3x (curator only), likely recovering several timeout
regressions.

### 7.2 Curator overhead on long SWE-bench tasks

SWE-bench tasks average 76 turns (vs 30 on terminal-bench). The
curator reads full raw.jsonl every turn, and its LLM call cost grows
with history length. At 100+ turns, each curator call processes a
large input. The passthrough threshold (skip if <10 turns and <40K
chars) helps early turns but doesn't address the long-tail overhead.

### 7.3 3x more timeouts than baseline

20/55 DHAv6 tasks timeout vs 6/55 baseline tasks (on the same 55
tasks). The harness overhead converts what would be close-but-successful
runs into timeouts.

---

## 8. Recommendations

### 8.1 Fix L2 max_tokens (the one-line fix)

Change `validator.task_understanding.max_tokens` from 500 to 4096.
The model works correctly once it has enough token budget for both
thinking (~2000 tokens) and the JSON response (~600 tokens). This
eliminates 100% of the L2 fallbacks and enables the task-understanding
check to actually function.

### 8.2 Re-run with fixed max_tokens

Re-run the full 500 tasks with `max_tokens=4096`. With L2 actually
working, it should catch shallow patches — potentially recovering
some of the 4 wrong-answer regressions. The timeout regressions
will also improve because L2 fallbacks currently waste two LLM
calls per fallback (first attempt + strict retry), doubling the
latency for nothing. With successful parses, only one call is needed.

### 8.3 Consider async curator

For long SWE-bench tasks (100+ turns), the curator call adds latency
per turn. An async design — start the curator while the generator is
running, have the result ready for the next turn — would eliminate
this latency.

### 8.4 Simplify L2 output format

If keeping L2, simplify the schema from 4 required fields to:
```json
{"decision": "PASS/REJECT", "reason": "one sentence"}
```
The current schema (`task_mechanism_quote`, `edit_gap`, `suggestion`)
is too complex for smaller models to produce reliably.

### 8.5 Complete the run

55/500 is too small for definitive conclusions. The tasks evaluated
may not be representative. Run the remaining ~445 tasks (with L2
disabled per recommendation 8.1).

---

## 9. Summary

| Finding | Detail |
|---------|--------|
| Token efficiency | **0.10x total tokens** — 10x reduction |
| Pass rate (overlap) | 45.5% vs 63.6% — **18 point regression** |
| New solves | 3 tasks |
| Regressions | 13 tasks (9 timeout, 4 wrong answer) |
| Net | **−10 tasks** |
| L2 validator | **Broken** — max_tokens=500 too low for thinking model; thinking exhausts budget, content=null, 1155 fallbacks |
| Overhead ratio | 2.29x (vs 1.48x on terminal-bench) |
| Root cause | L2 waste + curator overhead on long tasks → timeouts |
| Immediate fix | Set L2 max_tokens=4096, re-run full 500 tasks |
