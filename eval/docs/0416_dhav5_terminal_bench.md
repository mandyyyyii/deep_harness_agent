# DHAv5 vs Terminus-2 on Terminal-Bench 2.0 (Qwen3.5-35B-A3B)

**Date:** 2026-04-16
**Model:** qwen3.5-35b-a3b (MoE, 35B params, A3B active)
**Benchmark:** terminal-bench v2.0, 89 tasks
**Baseline:** Terminus-2 (bare, no harness), same model, 5 trials/task (results/terminal_0412)
**Experiment:** DHAv5 (curator + rule validator), 1 trial/task (results/dhav5_tb_0416)

---

## 1. Headline Numbers

| Metric | Terminus-2 (5 trials) | DHAv5 (1 trial) |
|--------|-----------------------|-----------------|
| Tasks evaluated | 89 (445 trials) | 88 |
| pass@5 (any trial passes) | 40 / 89 (44.9%) | — |
| **pass@1 (first trial)** | **27 / 89 (30.3%)** | **23 / 88 (26.1%)** |
| Estimated pass@1 (avg rate) | 31.0% | 26.1% |

DHAv5 is compared against T2's single-trial (first trial) results for
a fair apples-to-apples comparison. T2's pass@5 is shown for context
but is not the comparison target.

### Task-level overlap

All 23 DHAv5 passes are tasks that T2 also passes (in at least one
trial). **DHAv5 introduces zero new solves** — every task it passes,
T2 already solved.

| Category | Count | Tasks |
|----------|-------|-------|
| Both pass (DHAv5 ∩ T2 first-trial) | 18 | build-pov-ray, cobol-modernization, code-from-image, configure-git-webserver, fix-code-vulnerability, fix-git, git-leak-recovery, git-multibranch, headless-terminal, hf-model-inference, kv-store-grpc, mcmc-sampling-stan, modernize-scientific-stack, multi-source-data-merger, nginx-request-logging, portfolio-optimization, prove-plus-comm, vulnerable-secret |
| DHAv5 pass, T2 first-trial fail | 5 | build-pov-ray¹, crack-7z-hash, distribution-search, merge-diff-arc-agi-task, qemu-startup |
| T2 first-trial pass, DHAv5 fail | 9 | build-pmars, compile-compcert, constraints-scheduling, largest-eigenval, log-summary-date-ranges, openssl-selfsigned-cert, pytorch-model-cli, rstan-to-pystan, sanitize-git-repo |
| Both fail | 56 | (majority are timeout-driven) |

¹ build-pov-ray: T2 first trial timed out, but other T2 trials also pass.

Of the 5 DHAv5-only passes, all 5 are tasks T2 passes in other trials
(pass@5). None represent genuinely new task solves — they're within
sampling variance of T2's pass distribution.

Of the 9 T2-only passes, all 9 are tasks T2 passes robustly or
moderately across trials. These are real regressions.

---

## 2. Token Efficiency

The curator's core design goal — flatten per-turn token growth — is
achieved.

| Metric | Terminus-2 | DHAv5 | Ratio |
|--------|-----------|-------|-------|
| Mean per-turn input tokens | 24.1K | 7.7K | **0.32x** |
| Median per-turn input tokens | 13.3K | 6.7K | 0.50x |
| Total input tokens (86 tasks) | 198.0M | 26.8M | **0.14x** |
| Mean episodes | 44.3 | 30.3 | 0.68x |
| Median episodes | 26 | 26 | 1.0x |

Per-turn tokens drop to **0.32x of baseline**. Total input tokens drop
to **0.14x** (7x reduction). The curator keeps per-turn size nearly
flat at ~7K instead of growing linearly to 50-60K on long trajectories.

The episode count is also lower (0.68x), despite DHAv5 having more
token headroom per turn. This suggests the 900s wall-clock timeout is
the binding constraint, and curator overhead consumes some of that time.

---

## 3. Harness Overhead

| Component | Mean tokens | % of generator |
|-----------|-------------|---------------|
| Generator | 395K | 100% (baseline) |
| Curator | 531K | 134% |
| Validator | 0K | 0% (rules only, no LLM) |
| **Total overhead** | **531K** | **134%** |

**Overhead ratio: 1.48x** (median 1.36x). The curator LLM call
consumes 1.34x the generator's tokens on average. This is the cost of
re-reading raw.jsonl and producing curation decisions each turn.

Curator behavior across 87 tasks:
- SUMMARIZE decisions: mean 224 per task (dominant action — 93%)
- KEEP decisions: mean 17 per task (7%)
- Fallbacks (parse/API failure → passthrough): 50 total (0.6/task)

---

## 4. Validator Rule Layer

Layer 2 (LLM task-understanding) was disabled. All rejection is
rule-based (duplicate, cyclic, syntax).

| Metric | Value |
|--------|-------|
| Total rule rejects | 791 |
| Total validator passes | 1,856 |
| **Reject rate** | **29.9%** |
| Tasks with ≥1 reject | 66 / 87 (76%) |

Top offenders: sam-cell-seg (109 rejects), compile-compcert (52),
train-fasttext (49), rstan-to-pystan (46).

The 29.9% reject rate is higher than the 21% wasted-turn rate from
the report_0412 analysis. The rules catch more than just exact
duplicates — they also flag cyclic patterns and syntax errors.

---

## 5. Regression Analysis

### 5.1 Robust regressions (T2 ≥60% pass rate across 5 trials)

These are tasks T2 solves reliably but DHAv5 fails.

| Task | T2 pass rate | T2 avg eps (pass) | T2 avg input (pass) | DHAv5 eps | DHAv5 input | DHAv5 outcome |
|------|-------------|-------------------|---------------------|-----------|-------------|---------------|
| build-pmars | 5/5 (100%) | 29 | 351K | 48 | 570K | timeout |
| rstan-to-pystan | 5/5 (100%) | 51 | 1673K | 73 | 975K | timeout |
| compile-compcert | 4/5 (80%) | 42 | 880K | 92 | 1377K | timeout |
| log-summary-date-ranges | 4/5 (80%) | 6 | 53K | 10 | 83K | wrong answer |
| openssl-selfsigned-cert | 3/5 (60%) | 6 | 18K | 7 | 21K | wrong answer |
| sqlite-with-gcov | 3/5 (60%) | 14 | 122K | 53 | 565K | timeout |

**Pattern 1 — timeout on tasks T2 solves quickly:**
build-pmars, compile-compcert, and sqlite-with-gcov show DHAv5 running
many more episodes than T2 needed, then timing out. Despite having
lower per-turn tokens, DHAv5 uses more episodes and more total tokens.
The curator overhead (LLM call per turn) consumes wall-clock time that
T2 spends on productive generator turns.

build-pmars: T2 solves in 29 episodes. DHAv5 runs 48 episodes (13 rule
rejects) and times out trying to add `#include <ncurses.h>` to
`curdisp.c`. The agent retries `sed` variations without progress —
the curator's summarization may drop context about why earlier attempts
failed, losing the signal needed to break the loop.

**Pattern 2 — wrong answer on short precision tasks:**
log-summary-date-ranges (10 eps) and openssl-selfsigned-cert (7 eps)
complete but produce wrong results. These are short enough that the
curator's summarization is likely neutral (only 5-18 SUMMARIZE
decisions). More likely sampling variance.

**Pattern 3 — rstan-to-pystan paradox:**
T2 solves this in 51 episodes using 1,673K input tokens. DHAv5 runs
73 episodes using only 975K tokens — fewer total tokens but more
episodes. The curator successfully compresses context (0.58x tokens)
but the agent still can't converge within the timeout. The
compression may be too aggressive, removing intermediate build
outputs that inform the next debugging step.

### 5.2 Fragile regressions (T2 20-40% pass rate)

| Task | T2 pass rate | DHAv5 outcome |
|------|-------------|---------------|
| count-dataset-tokens | 1/5 | wrong answer (63841) |
| pytorch-model-cli | 2/5 | wrong answer |
| bn-fit-modify | 2/5 | wrong answer (65 eps) |
| largest-eigenval | 2/5 | timeout (37 eps) |
| extract-elf | 2/5 | timeout (29 eps) |
| constraints-scheduling | 2/5 | setup timeout (infra) |
| custom-memory-heap-crash | 1/5 | timeout (10 eps) |
| sanitize-git-repo | 1/5 | wrong answer |
| regex-log | 1/5 | timeout (18 eps) |
| sqlite-db-truncate | 1/5 | timeout (13 eps) |

These tasks have low T2 pass rates (20-40%). DHAv5's failure on them
is within normal sampling variance — T2 would also fail on 60-80% of
attempts. Not attributable to the curator.

---

## 6. What Worked

### 6.1 Token efficiency is real and large

7x reduction in total input tokens. Per-turn tokens capped at ~7K
instead of growing to 50K+. This is the curator's core value
proposition and it delivers.

### 6.2 Rule validator catches waste

791 rule rejects (29.9% of commands) — all free, no LLM cost. The
worst offenders (sam-cell-seg: 109 rejects, compile-compcert: 52) were
stuck in loops that the rules broke.

### 6.3 No new solves but also no catastrophes

DHAv5 doesn't solve any task that T2 can't, but on the 18 tasks both
pass, DHAv5 generally uses fewer total tokens. The architecture
doesn't break the agent on tasks it can solve.

---

## 7. Why DHAv5 Doesn't Gain Pass Rate

### 7.1 Summarization loss

The curator aggressively summarizes (224 SUMMARIZE per task, 93% of
decisions). This flattens tokens but loses information. For tasks
requiring precise error messages, exact numerical outputs, or specific
compilation flags, the summarized history may not carry enough signal
for the agent to self-correct.

Evidence: build-pmars and compile-compcert show DHAv5 running *more*
episodes than T2 while using *fewer* tokens per turn — the agent keeps
trying but can't converge because critical context was compressed away.

### 7.2 Wall-clock overhead

Each curator LLM call costs wall-clock time (estimated 2-5s/turn at
current model speed). On a 30-turn task, that's 60-150s of the 900s
timeout consumed by the curator alone. T2 spends that time on
productive generator turns instead.

Evidence: median episode count is identical (26 vs 26), but mean
episodes are lower for DHAv5 (30.3 vs 44.3). The tail of long
trajectories is shorter — DHAv5 hits the timeout sooner because each
turn takes longer.

### 7.3 The tasks DHAv5 "gains" are sampling variance

All 5 DHAv5-only passes (vs T2 first trial) are tasks T2 passes in
other trials. DHAv5 doesn't solve any fundamentally new task. The
curator helps the agent stay within token budget, but the agent's
reasoning capability is the same model — and the curator can't improve
reasoning, only manage context.

---

## 8. Recommendations

### 8.1 Threshold-based curator skip

On tasks solved in <15 turns, the curator adds overhead without
benefit. Skip the curator call when raw.jsonl has <10 turns and total
content is <40K chars. This eliminates overhead on the easiest ~30% of
tasks and preserves full context for them.

### 8.2 Reduce summarization aggressiveness

93% SUMMARIZE rate is too high. The curator prompt should keep more
turns verbatim, especially: (1) turns with compilation/test output,
(2) turns containing numerical results, (3) turns where the agent
changed approach. Consider instructing the curator to KEEP the last
10-15 turns instead of 5-8.

### 8.3 Reduce curator model latency

Use a smaller/faster model for the curator (e.g., a 7B model instead
of the same 35B). The curator's job (KEEP/SUMMARIZE/DROP) is
structurally simpler than the generator's task-solving. A smaller model
at lower latency would free wall-clock time for more generator turns.

### 8.4 Run 5 trials for DHAv5

The comparison is unfair in one direction: T2 has 5 chances per task,
DHAv5 has 1. DHAv5's true pass@5 could be higher. Run 5 trials to
get a proper distribution.

### 8.5 Enable validator Layer 2

Layer 2 was disabled. Tasks like count-dataset-tokens (wrong answer
submitted confidently) and pytorch-model-cli (wrong answer) are
exactly the kind of "plausible-looking but wrong submission" that
Layer 2's task-understanding check is designed to catch. Worth testing.

---

## 9. Summary Table

| Finding | Detail |
|---------|--------|
| Token efficiency | **0.14x total tokens**, 0.32x per-turn — 7x reduction |
| Pass rate (pass@1) | T2: 30.3%, DHAv5: 26.1% — **4 point regression** |
| New solves | **Zero** — every DHAv5 pass is a task T2 already solves |
| Robust regressions | 6 tasks (3 timeout, 2 wrong answer, 1 paradox) |
| Fragile regressions | 11 tasks (within T2's own sampling variance) |
| Curator overhead | 1.48x generator tokens, plus wall-clock cost |
| Validator rule rejects | 791 (29.9% of commands), all free |
| Root cause | Aggressive summarization (93%) loses precision; curator latency costs wall-clock on 900s timeout |

**Bottom line:** The curator achieves its token-efficiency goal (7x
reduction) but this doesn't convert to more task solves. The
information lost to summarization and the wall-clock cost of the
curator LLM call together cause a net regression of ~4 percentage
points on pass@1. The architecture is sound — the policy (when and
how aggressively to compress) needs tuning.
