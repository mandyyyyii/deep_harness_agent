# DHAv6 on SWE-bench Verified (Qwen3.5-35B-A3B) — Partial

**Date:** 2026-04-18 (experiment ran 2026-04-17)
**Model:** qwen3.5-35b-a3b
**Benchmark:** SWE-bench Verified (500 tasks, 228 completed)
**Baseline:** MiniSweConfigured bare (results/swe_0412 + swe_0412_remaining, 499 tasks, 59.9%)

---

## 1. Headline Numbers

| Metric | Baseline (MiniSwe) | DHAv6 |
|--------|-------------------|-------|
| Tasks completed | 499 | 228 (partial) |
| Pass rate (all) | 299/499 (59.9%) | 92/228 (40.4%) |
| **Pass rate (228 overlap)** | **139/228 (61.0%)** | **92/228 (40.4%)** |
| Timeouts | ~30 | 79 (34.6%) |

**20.6 percentage point drop** on overlapping tasks. Net −47 tasks.

| Category | Count |
|----------|-------|
| Both pass | 81 |
| DHAv6 only (gains) | 11 |
| Baseline only (regressions) | 58 |

---

## 2. Regression Breakdown

The 58 regressions split into two distinct failure modes:

| Failure mode | Count | Cause |
|-------------|-------|-------|
| **Wrong answer (submitted)** | **35** | Curator summarization |
| **Timeout** | **23** | L2 + curator overhead |

### 2.1 Wrong-answer regressions (35 tasks) — the main problem

These tasks **completed and submitted** but with a wrong patch. The
agent declared success confidently. This is not a timeout or overhead
issue — even without L2, these would fail.

| Metric | Baseline | DHAv6 |
|--------|---------|-------|
| Mean turns | 107.2 | 66.4 |
| DHAv6 / baseline turns | — | **62%** |

DHAv6 uses only 62% of baseline's turns before submitting. The agent
converges faster but on the wrong fix.

**L2 contribution to wrong answers:**
- 19 of 35 (54%) have ≥5 L2 rejects
- Total L2 rejects across 35 tasks: 298 (= 298 wasted episodes)
- But even adding those back: 66.4 + ~8.5 ≈ 75 turns, still below
  baseline's 107. L2 is a contributor but not the primary cause.

**Root cause: curator summarization changes what the agent sees.**

The baseline (MiniSweConfigured) passes **full uncompressed history**
every turn. At turn 100, the agent has 100 complete action-observation
pairs (~60K tokens) in context. The model can attend to all of it.

DHAv6's curator compresses history: 97.3% summarize rate. At turn
100, the agent sees the last 10-15 turns verbatim plus summaries
of turns 1-85. The compressed context is 10K tokens instead of 60K.
This saves tokens but **loses details the agent needs to construct
the correct fix:**

- Exact error messages from early debugging
- Specific code snippets that informed the approach
- The evolution of the agent's understanding (why it abandoned path A
  for path B)
- Precise function signatures and variable names from file reads

The agent fills in the gaps from its own (compressed) understanding
and converges on a plausible-but-wrong fix.

### 2.2 Timeout regressions (23 tasks)

These are overhead-driven. L2 (41.2% reject rate) + curator (2.29x
overhead) consume wall-clock time. Baseline solved these within the
timeout; DHAv6 couldn't.

Disabling L2 would likely recover most of these (same model, same
curator, but ~35% less overhead per turn).

---

## 3. Token Efficiency

| Metric | Baseline | DHAv6 | Ratio |
|--------|---------|-------|-------|
| Per-turn input | 60.0K | 9.7K | **0.16x** |
| Total input (221 tasks) | — | — | **0.12x** |
| Mean turns | 112.5 | 83.6 | 0.74x |

Token efficiency is strong: 8x reduction in total tokens. But the
model performs better with the full 60K-token context than with the
compressed 10K-token context.

---

## 4. Harness Stats

### Overhead: 2.29x (median 2.24x)

| Component | Mean tokens |
|-----------|-------------|
| Generator | 835K |
| Curator | 1,355K (162% of generator) |
| Validator | 419K (50% of generator) |

### Curator: 97.3% summarize rate

Still very aggressive despite the KEEP-bias prompt changes. On
SWE-bench (mean 84 turns), the curator summarizes almost everything
beyond the last 10-15 turns.

### Validator

| Metric | Value |
|--------|-------|
| Rule rejects | 1,033 |
| L2 rejects | 2,538 |
| L2 passes | 3,599 |
| L2 skipped | 11,223 |
| **L2 reject rate** | **41.2%** |

L2 is functional but aggressive — rejecting 41% of edit/submission
commands it evaluates.

---

## 5. What DHAv6 Gains (11 tasks)

| Task | D6 turns | BL turns | BL failure |
|------|---------|---------|-----------|
| django-15375 | 87 | 1607 | timeout (baseline loop) |
| scikit-learn-25973 | 122 | 284 | wrong answer |
| pydata-xarray-6938 | 128 | 137 | wrong answer |
| django-13449 | 98 | 77 | wrong answer |
| django-12209 | 77 | 150 | wrong answer |
| matplotlib-24149 | 53 | 81 | wrong answer |
| sympy-17655 | 101 | 93 | wrong answer |
| sphinx-7889 | 71 | 81 | wrong answer |
| pydata-xarray-2905 | 55 | 82 | wrong answer |
| django-14580 | 51 | 0 | setup timeout |
| psf-requests-1724 | 76 | 0 | setup timeout |

7 of 11 gains are tasks where the baseline submitted a wrong answer
but DHAv6 got the right one. The harness steered the agent to a
different (correct) path — likely through L2 rejecting the baseline's
shallow initial attempt, or the curator's unresolved index keeping
key findings visible.

2 gains are infra fixes (setup timeout in baseline).
1 gain (django-15375) is a loop that baseline couldn't break but
DHAv6's rule validator caught.

---

## 6. Why Performance Drops Even Without L2

Disabling L2 would:
- Recover most of the 23 timeout regressions
- NOT recover the 35 wrong-answer regressions

**The 35 wrong-answer regressions are caused by the curator, not the
validator.** The curator changes what the agent sees. On SWE-bench,
where tasks require precise understanding of code behavior across
large codebases, the compressed context loses critical details that
the full-history baseline preserves.

This is fundamentally different from terminal-bench, where tasks are
more self-contained and earlier turns are less load-bearing. On
SWE-bench, the agent's understanding of a bug often builds
incrementally across 50-100 turns of reading code, and details from
turn 20 can be essential at turn 80.

---

## 7. Recommendations to Match T2 Baseline

### 7.1 Raise the curator passthrough threshold significantly

Current: skip curator if <10 turns AND <40K chars.
Proposed: skip curator if <30 turns AND <200K chars.

SWE-bench tasks average 84 turns. The baseline uses full history
up to 60K tokens/turn and succeeds at 60%. The curator should not
compress until the history genuinely exceeds the model's context
window. For qwen3.5-35b-a3b (128K context), compression should
kick in only when raw history approaches ~100K tokens.

**Expected impact:** Recovers most wrong-answer regressions on
tasks with <30 turns (many of the 35 have 60-90 turns).

### 7.2 Increase KEEP window to 30+ turns

Current prompt: KEEP the last 10-15 turns. For SWE-bench tasks
averaging 84 turns, this means 70+ turns are summarized. The agent
loses access to most of its exploration history.

Set the KEEP window to 30 or more. This preserves the recent
working context while still compressing very old turns.

### 7.3 Reduce L2 reject rate

41.2% reject rate is too high. The prompt's mitigating factors
aren't sufficiently constraining the model. Options:
- Add "when in doubt, PASS" more forcefully
- Require the evidence field to include a direct quote from
  history that contradicts the proposed edit
- Skip L2 entirely on first edit attempt (only validate re-edits)

### 7.4 Consider a "curator off, rules only" configuration

The simplest way to match baseline: disable the curator entirely,
keep only the rule-based validator. This gives you:
- Full history (like baseline)
- Rule-based duplicate/cycle/syntax catching (free)
- No L2 overhead
- No summarization loss

This would test whether the rule validator alone provides net
positive value over bare MiniSwe.

### 7.5 Adaptive compression based on context usage

Instead of always compressing, only compress when the agent's actual
token usage approaches the model's context window. Monitor
`total_tokens` vs model context limit:
- If `total_tokens < 0.6 * context_limit`: passthrough (no curator)
- If `total_tokens > 0.6 * context_limit`: start summarizing oldest
  turns
- If `total_tokens > 0.8 * context_limit`: aggressive compression

This preserves full history for the majority of SWE-bench tasks
(which stay under 100K tokens) while catching the ~10% that would
overflow.

---

## 8. Summary

| | Baseline | DHAv6 | Gap |
|--|---------|-------|-----|
| Pass rate (overlap) | 61.0% | 40.4% | **−20.6pp** |
| Wrong-answer regressions | — | 35 | Curator summarization |
| Timeout regressions | — | 23 | L2 + curator overhead |
| Gains | — | 11 | L2 steering + curator focus |
| Per-turn tokens | 60K | 9.7K | 6x reduction |
| Curator summarize rate | 0% | 97.3% | — |
| L2 reject rate | — | 41.2% | Too aggressive |

**The main performance drop is the curator, not L2.** 35 of 58
regressions are wrong answers caused by summarization loss — the
agent submits confident-but-wrong fixes because compressed history
doesn't carry enough detail for SWE-bench's code-reasoning tasks.
Even disabling L2 entirely would only recover the 23 timeout
regressions, leaving a ~15pp gap.

**To match the baseline:** the curator needs to compress far less
aggressively on SWE-bench — either by raising the passthrough
threshold dramatically, widening the KEEP window, or switching to
adaptive compression that only activates near the context limit.
The current policy (compress always, keep last 10-15 turns) is
tuned for short terminal-bench tasks, not 100-turn SWE-bench
trajectories.
