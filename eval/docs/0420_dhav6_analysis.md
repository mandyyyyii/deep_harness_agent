# DHAv6 0420 — Terminal-Bench & SWE-bench Analysis

**Date:** 2026-04-20
**Model:** qwen3.5-35b-a3b
**Runs:** dhav6_tb_0420 (65/89 tasks, partial), dhav6_swe_0420 (47/500 tasks, partial)
**Baselines:** T2 terminal_0412 (pass@5), MiniSwe swe_0412
**Prior:** DHAv6 0419, DHAv6 0417

---

## 1. Headline Numbers

### Terminal-Bench

| Run | Tasks | Pass | Rate | Overhead | Curator sum% | L2 rej% |
|-----|-------|------|------|----------|-------------|---------|
| T2 pass@5 | 89 | 40 | 44.9% | — | — | — |
| DHAv6 0417 | 89 | 22 | 24.7% | 1.64x | 82.4% | 34.8% |
| DHAv6 0419 | 89 | 25 | 28.1% | 1.26x | 58.6% | 26.1% |
| **DHAv6 0420** | **65** | **18** | **27.7%** | **1.67x** | **71.1%** | **32.5%** |

0420 is partial (65/89). On the 65 overlapping tasks with 0419,
both get 18 passes — identical pass count, different tasks.

### SWE-bench

| Run | Tasks | Pass | Rate | Overhead | Curator sum% | L2 rej% |
|-----|-------|------|------|----------|-------------|---------|
| Baseline | 499 | 299 | 59.9% | — | 0% | — |
| DHAv6 0419 | 139 | 57 | 41.0% | 1.72x | 70.0% | 37.0% |
| **DHAv6 0420** | **47** | **25** | **53.2%** | **1.98x** | **82.1%** | **42.2%** |
| Baseline (47 overlap) | 47 | 30 | 63.8% | — | — | — |

SWE 0420 shows 53.2% — the closest to baseline yet. But only 47
tasks (may not be representative). Gap to baseline on overlap is
−10.6pp (53.2% vs 63.8%), improved from 0419's −20.9pp.

---

## 2. Terminal-Bench Detail

### 2.1 Task churn: gains and losses cancel out

On the 65 tasks that ran in both 0419 and 0420:

| | Count | Tasks |
|--|-------|-------|
| Gained vs 0419 | 4 | code-from-image, crack-7z-hash, merge-diff-arc-agi-task, **query-optimize** |
| Lost vs 0419 | 4 | build-pov-ray, fix-code-vulnerability, headless-terminal, tune-mjcf |

**query-optimize is a new solve** — T2 fails all 5 trials. This is
the second new solve after tune-mjcf (0419), though tune-mjcf didn't
reproduce in 0420. DHAv6 solved query-optimize in 32 turns with
12 rule rejects, 0 L2 rejects, and only 1.06x overhead.

### 2.2 Stability analysis (3 runs on 65 overlapping tasks)

| Category | Count | Tasks |
|----------|-------|-------|
| **Stable passes** (all 3 runs) | 11 | cobol-modernization, configure-git-webserver, distribution-search, fix-git, git-multibranch, kv-store-grpc, log-summary-date-ranges, mcmc-sampling-stan, modernize-scientific-stack, portfolio-optimization, prove-plus-comm |
| **Unstable** (pass in some) | 14 | build-pov-ray, code-from-image, count-dataset-tokens, crack-7z-hash, fix-code-vulnerability, headless-terminal, hf-model-inference, largest-eigenval, merge-diff-arc-agi-task, multi-source-data-merger, pypi-server, qemu-startup, query-optimize, tune-mjcf |

**11 tasks pass consistently.** 14 tasks flip between pass and fail
across runs — high variance driven by sampling, L2 rejection
randomness, and curator compression differences.

Unstable task patterns:

| Task | 0417 | 0419 | 0420 | Pattern |
|------|------|------|------|---------|
| hf-model-inference | ✗ | ✓ | ✓ | Stabilizing |
| multi-source-data-merger | ✗ | ✓ | ✓ | Stabilizing |
| pypi-server | ✗ | ✓ | ✓ | Stabilizing |
| tune-mjcf | ✗ | ✓ | ✗ | One-off |
| query-optimize | ✗ | ✗ | ✓ | One-off |
| build-pov-ray | ✗ | ✓ | ✗ | One-off |
| headless-terminal | ✗ | ✓ | ✗ | One-off |
| code-from-image | ✗ | ✗ | ✓ | One-off |
| qemu-startup | ✓ | ✗ | ✗ | Lost |
| count-dataset-tokens | ✓ | ✗ | ✗ | Lost |
| largest-eigenval | ✓ | ✗ | ✗ | Lost |

3 tasks are stabilizing (pass in 2 of 3 runs). 6 are one-offs
(pass in exactly 1 run). 3 appear to have degraded (pass only in
0417, fail in both 0419 and 0420).

### 2.3 Overhead regression

Overhead increased from 1.26x (0419) back to 1.67x (0420). Curator
summarize rate went from 58.6% to 71.1%, and L2 reject rate from
26.1% to 32.5%. This is likely due to task mix (the 65 tasks in
0420 may skew harder/longer than the 24 tasks not yet completed),
not a code regression.

### 2.4 New solves across all DHAv6 runs

| Task | First solved | T2 pass@5 | Status |
|------|-------------|----------|--------|
| tune-mjcf | 0419 | 0/5 | Did not reproduce in 0420 |
| query-optimize | 0420 | 0/5 | New this run |

Two tasks that T2 never solves in 5 trials. Both are one-off solves
so far (not reproduced in a second run). DHAv6 can solve tasks T2
cannot, but not reliably yet.

---

## 3. SWE-bench Detail

### 3.1 Gap narrowing

| Metric | 0419 (139 tasks) | 0420 (47 tasks) |
|--------|-----------------|-----------------|
| DHAv6 pass rate | 41.0% | 53.2% |
| Baseline pass rate (overlap) | 61.9% | 63.8% |
| **Gap** | **−20.9pp** | **−10.6pp** |
| Regressions | 35 | 8 |
| — Timeout | 19 | 3 |
| — Wrong answer | 16 | 5 |
| Gains | 6 | 3 |

The gap halved from 20.9pp to 10.6pp. Caveat: only 47 tasks —
the sample may not be representative. The remaining ~450 tasks
could shift this substantially.

### 3.2 Task-level

| Category | Count |
|----------|-------|
| Both pass | 22 |
| DHAv6 only (gains) | 3 |
| Baseline only (regressions) | 8 |
| Net | −5 |

**3 gains:** matplotlib-24149 (39 turns), psf-requests-2317 (35 turns),
sympy-23413 (63 turns). All relatively short — solved before curator
compression becomes aggressive.

**8 regressions:** 3 timeout, 5 wrong answer.

### 3.3 Wrong-answer regressions

| Task | Turns | L2 rejects |
|------|-------|-----------|
| pydata-xarray-6461 | 89 | 37 |
| astropy-7166 | 54 | 14 |
| django-11333 | 111 | 14 |
| scikit-learn-10297 | 43 | 9 |
| pytest-7432 | 47 | 7 |

All 5 have L2 rejects. pydata-xarray-6461 has 37 L2 rejects —
extremely high. The L2 is likely interfering with the agent's
attempts to write the fix.

### 3.4 Token efficiency

| Metric | Baseline | DHAv6 0420 | Ratio |
|--------|---------|-----------|-------|
| Per-turn input | 48.6K | 11.8K | **0.24x** |
| Total input (47 tasks) | — | — | **0.25x** |
| Mean turns | 88.7 | 92.7 | 1.05x |

4x token reduction maintained. Turns are roughly equal — the agent
is getting the same number of attempts, just with compressed context.

---

## 4. Progression Summary

### Terminal-Bench across all DHAv6 runs

| Metric | 0417 | 0419 | 0420 (partial) |
|--------|------|------|----------------|
| Pass rate | 24.7% | 28.1% | 27.7% |
| Stable passes | — | — | 11 (all 3) |
| New solves (vs T2) | 0 | 1 (tune-mjcf) | 1 (query-optimize) |
| Overhead | 1.64x | 1.26x | 1.67x |
| L2 reject rate | 34.8% | 26.1% | 32.5% |

Pass rate stabilized around 27-28% — a consistent +3pp over the
initial 0417 run, but still −5pp below T2 first-trial (32.6%).

The two new solves (tune-mjcf, query-optimize) demonstrate the
harness can steer agents past dead ends. Both tasks had T2 stuck
in unproductive loops; the rule validator + L2 forced exploration
of alternative approaches.

### SWE-bench across DHAv6 runs

| Metric | 0419 (139 tasks) | 0420 (47 tasks) |
|--------|-----------------|-----------------|
| Pass rate | 41.0% | 53.2% |
| Gap to baseline | −20.9pp | −10.6pp |
| Wrong-answer regressions | 16 | 5 |

Trending better, but 47 tasks is too small to draw conclusions.
The wrong-answer regression rate dropped from 11.5% to 10.6%.

### Key metrics evolution

| Metric | DHAv5 | 0417 | 0419 | 0420 TB | 0420 SWE |
|--------|-------|------|------|---------|----------|
| Curator sum% | 93% | 82% | 59% | 71% | 82% |
| L2 reject% | 0% (broken) | 35% | 26% | 33% | 42% |
| Overhead | 1.48x | 1.64x | 1.26x | 1.67x | 1.98x |

Overhead and L2 reject rate fluctuate between runs. The 0419 run
had the best numbers; 0420 is higher (task mix effect).

---

## 5. High-variance observation

The most striking finding is the **high variance between runs**.
14 of 25 passing tasks (56%) are unstable — they flip between pass
and fail across three runs on the same benchmark with the same code.

This means single-trial pass rate is a noisy metric for DHAv6.
The harness introduces two sources of randomness beyond the
generator's sampling:
1. **Curator LLM decisions** — which turns to summarize/keep
   varies per run
2. **L2 LLM decisions** — which edits to reject varies per run

Combined with the generator's own sampling variance, single-trial
results are unreliable for measuring harness impact.

**Recommendation:** The next comparison should use 5 trials per
task (like the T2 baseline). A pass@5 comparison would show whether
DHAv6 expands the set of solvable tasks, which is the real question
— not whether any single trial matches T2's first trial.

---

## 6. Where DHAv6 provides clear value

1. **New solves:** tune-mjcf (0419) and query-optimize (0420) — tasks
   T2 fails in all 5 trials. The harness can steer the agent past
   dead ends that the bare agent cannot escape.

2. **Token efficiency:** 4x reduction on SWE, ~4x on TB. Per-turn
   tokens are ~10-15K instead of 50-60K.

3. **Loop breaking:** Rule validator catches duplicates and cycles
   for free. 436-554 rule rejects per TB run.

4. **Stable core:** 11 TB tasks pass in all 3 runs. The harness
   doesn't break the agent's core capability.

## 7. Where DHAv6 still falls short

1. **Pass rate vs T2:** 27-28% vs 32.6% (first-trial) on TB.
   53% vs 64% on SWE (partial). The gap persists.

2. **High variance:** 56% of passing tasks are unstable. Hard to
   distinguish signal from noise without multi-trial runs.

3. **L2 over-rejection:** 32-42% reject rate is too aggressive.
   build-pov-ray got 69 L2 rejects in 0420 (vs 5 in 0419 when it
   passed). pydata-xarray-6461 got 37 L2 rejects on SWE.

4. **SWE curator compression:** 82% summarize rate on SWE is still
   too high for 90-turn code-reasoning tasks.

---

## 8. Recommendations

### 8.1 Run 5 trials on TB

The single-trial variance makes iteration on the harness unreliable.
A 5-trial TB run would give pass@5 directly comparable to T2's 44.9%.
Expected: DHAv6 pass@5 should be ~35-40% based on the union of tasks
that pass in at least one of the 3 existing runs (11 stable + up to
14 unstable = potentially 25 unique tasks).

### 8.2 Cap L2 rejects per trajectory

69 L2 rejects on build-pov-ray is pathological. Consider a per-task
cap (e.g., max 10 L2 rejects per trajectory). After the cap, L2
auto-passes all remaining commands. This bounds the cost of
over-rejection.

### 8.3 Complete the SWE run

47 tasks is insufficient. The 53.2% rate is promising but may not
hold on the full 500.

### 8.4 Adaptive curator for SWE

SWE 0420 has 82% summarize rate — back to DHAv5 levels. The
passthrough threshold (<10 turns, <40K chars) barely helps on SWE
where tasks average 90 turns. Raise to <30 turns or use
context-limit-based adaptive compression.
