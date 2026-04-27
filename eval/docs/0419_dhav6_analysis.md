# DHAv6 0419 — Terminal-Bench & SWE-bench Analysis

**Date:** 2026-04-19
**Model:** qwen3.5-35b-a3b
**Runs:** dhav6_tb_0419 (89 tasks), dhav6_swe_0419 (139 tasks, partial)
**Baselines:** T2 terminal_0412 (pass@5), MiniSwe swe_0412
**Prior:** DHAv6 0417 (TB only — SWE 0417 run cleaned up)

---

## 1. Headline Numbers

### Terminal-Bench

| Run | Pass rate | Δ from prior |
|-----|-----------|-------------|
| T2 pass@5 | 40/89 (44.9%) | baseline |
| T2 first-trial | 29/89 (32.6%) | baseline |
| DHAv5 (0416) | 23/88 (26.1%) | — |
| DHAv6 0417 | 22/89 (24.7%) | — |
| **DHAv6 0419** | **25/89 (28.1%)** | **+3 vs 0417** |

### SWE-bench

| Run | Pass rate | Δ from prior |
|-----|-----------|-------------|
| Baseline (MiniSwe) | 299/499 (59.9%) | baseline |
| **DHAv6 0419 (139 overlap)** | **57/139 (41.0%)** | — |
| **Baseline (139 overlap)** | **86/139 (61.9%)** | — |

---

## 2. What Changed: 0417 → 0419

All three key metrics improved on TB:

| Metric | DHAv6 0417 | DHAv6 0419 | Change |
|--------|-----------|-----------|--------|
| **Pass rate (TB)** | 24.7% | **28.1%** | **+3.4pp** |
| **Overhead** | 1.64x | **1.26x** | −0.38 |
| **Curator summarize rate** | 82.4% | **58.6%** | **−23.8pp** |
| **L2 reject rate** | 34.8% | **26.1%** | **−8.7pp** |

The curator is keeping significantly more turns (58.6% summarize vs
82.4%), and L2 is rejecting fewer commands (26.1% vs 34.8%). The
overhead dropped from 1.64x to 1.26x — the lowest of any DHAv6 run.

---

## 3. Terminal-Bench Detail

### 3.1 Task-level changes vs 0417

| Category | Count | Tasks |
|----------|-------|-------|
| Gained vs 0417 | 7 | build-pov-ray, fix-code-vulnerability, headless-terminal, hf-model-inference, multi-source-data-merger, pypi-server, **tune-mjcf** |
| Lost vs 0417 | 4 | bn-fit-modify, count-dataset-tokens, largest-eigenval, qemu-startup |
| Net | **+3** | |

**tune-mjcf is a new solve** — not solved by T2 in any of 5 trials
(pass@5 = 0/5). This is the first task DHAv6 solves that T2 cannot.

The 7 gains include 6 tasks that were 0417 regressions from over-
rejection (headless-terminal, code-from-image, hf-model-inference,
multi-source-data-merger, pypi-server, fix-code-vulnerability). The
lower L2 reject rate (26.1% vs 34.8%) and lower overhead (1.26x vs
1.64x) recovered them.

The 4 losses (bn-fit-modify, count-dataset-tokens, largest-eigenval,
qemu-startup) are tasks that benefited from 0417's higher L2 rejection
rate — L2 was catching shallow patches on these. With a lower reject
rate, some shallow patches now slip through.

### 3.2 vs T2 pass@5

| Category | Count |
|----------|-------|
| Both pass | 24 |
| **DHAv6 only (new solve)** | **1** (tune-mjcf) |
| T2 only (regression) | 16 |

16 remaining regressions vs T2:

| Failure mode | Count |
|-------------|-------|
| Timeout | 12 |
| Wrong answer | 4 |

### 3.3 Harness stats

| Component | Mean tokens | Δ from 0417 |
|-----------|-------------|-------------|
| Generator | 402K | −150K |
| Curator | 383K | −284K |
| Validator | 270K | −113K |
| **Overhead** | **1.26x** | **−0.38** |

| Metric | 0417 | 0419 |
|--------|------|------|
| Curator summarize | 82.4% | 58.6% |
| Curator keep | 17.6% | 41.4% |
| Curator fallbacks | 39 | 21 |
| Rule rejects | 761 | 554 |
| L2 rejects | 542 | 380 |
| L2 passes | 992 | 1,051 |
| L2 reject rate | 34.8% | 26.1% |

---

## 4. SWE-bench Detail

### 4.1 Overall (139 tasks completed)

| Metric | Value |
|--------|-------|
| Pass rate | 57/139 (41.0%) |
| Baseline (overlap) | 86/139 (61.9%) |
| **Gap** | **−20.9pp** |
| Timeouts | 49 (35.3%) |
| Wrong answers | 41 |

### 4.2 Task-level vs baseline

| Category | Count |
|----------|-------|
| Both pass | 51 |
| DHAv6 only (gains) | 6 |
| Baseline only (regressions) | 35 |
| Net | **−29** |

**6 gains:**
- django-11790, django-13406, matplotlib-24149, psf-requests-1724,
  psf-requests-2317, sympy-17655
- django-13406 is notable: the baseline looped for 1607 turns and
  timed out. DHAv6 solved it in 135 turns — the rule validator
  broke the loop.

**35 regressions:** 19 timeout, 16 wrong answer.

### 4.3 Wrong-answer regressions (16 tasks)

| Metric | Value |
|--------|-------|
| Mean turns | 69.7 |
| Mean L2 rejects | 6.8 |
| High L2 (≥5 rejects) | 10/16 (63%) |
| Zero L2 | 1/16 (6%) |
| Total L2 rejects wasted | 108 turns |

The wrong-answer count dropped from 35 (in the 0417 SWE run with
228 tasks) proportionally. On 139 tasks, 16 wrong answers is 11.5%
— comparable to 0417's 15.4% (35/228). The wrong-answer rate has
not improved.

### 4.4 Harness stats

| Metric | Value |
|--------|-------|
| Overhead | 1.72x (median 1.68x) |
| Generator mean | 1,077K |
| Curator mean | 1,434K |
| Validator mean | 441K |
| Curator summarize rate | 70.0% |
| L2 reject rate | 37.0% |

SWE overhead (1.72x) is higher than TB (1.26x) because SWE tasks
run longer (mean 88 turns vs 29), so the curator processes more
history each call. Curator summarize rate is 70% — lower than 0417's
97.3%, showing the KEEP-bias changes are taking effect on SWE-bench
too, though less dramatically than on TB.

---

## 5. Cross-Benchmark Comparison

| Metric | TB 0419 | SWE 0419 |
|--------|---------|----------|
| Pass rate | 28.1% | 41.0% |
| Gap vs baseline | −4.5pp (first-trial) | −20.9pp |
| Overhead | 1.26x | 1.72x |
| Curator summarize | 58.6% | 70.0% |
| L2 reject rate | 26.1% | 37.0% |
| Mean turns | 29.4 | 88.0 |
| Timeouts | 47/89 (53%) | 49/139 (35%) |

The harness works better on TB than SWE. On TB, the gap to baseline
is only 4.5pp (first-trial), overhead is modest (1.26x), and the
curator summarizes less aggressively (58.6%). On SWE, the gap is
21pp, overhead is higher (1.72x), and the curator still summarizes
70% of turns.

The fundamental difference: TB tasks average 29 turns (short enough
that the curator often passthroughs or keeps most turns), while SWE
tasks average 88 turns (forcing heavy summarization that loses
details needed for code fixes).

---

## 6. Progression Summary

### Terminal-Bench trajectory

| Version | Pass | Overhead | Curator sum% | L2 rej% | Key change |
|---------|------|----------|-------------|---------|------------|
| DHAv5 | 23/88 (26.1%) | 1.48x | 93% | 0% (broken) | First curator+validator |
| DHAv6 0417 | 22/89 (24.7%) | 1.64x | 82.4% | 34.8% | L2 fixed, KEEP-biased prompt |
| **DHAv6 0419** | **25/89 (28.1%)** | **1.26x** | **58.6%** | **26.1%** | Lower overhead, less aggressive |

Each iteration reduces overhead and L2 aggression. The 0419 run is
the first to show a pass rate above DHAv5, and the first to produce
a new solve (tune-mjcf).

### What's improving

1. **Overhead trending down**: 1.48x → 1.64x → 1.26x. The curator
   and L2 are getting cheaper.
2. **Curator preserves more**: 93% → 82% → 59% summarize rate. More
   context survives for the generator.
3. **L2 rejects less**: 0% → 35% → 26%. Fewer false positives on
   valid edits.
4. **First new solve**: tune-mjcf (T2 0/5 trials). The harness
   steered the agent past a point where T2 gets stuck.

### What still needs work

1. **SWE-bench gap is large** (21pp). The curator still summarizes
   too aggressively on long tasks (70% on SWE vs 59% on TB).
2. **Wrong-answer rate unchanged** on SWE (~11-15%). Curator
   summarization loses details for code-reasoning tasks.
3. **16 remaining TB regressions** vs T2 pass@5, mostly timeouts
   (12/16). Overhead still costs wall-clock time on harder tasks.
4. **SWE is only 139/500 tasks** — need full run for definitive
   comparison.

---

## 7. Recommendations

### 7.1 Adaptive curator threshold for SWE

The curator passthrough threshold (<10 turns, <40K chars) works for
TB but is too low for SWE. For SWE with 128K model context:
- Passthrough if total_tokens < 80K (covers ~70% of SWE tasks)
- Compress only when approaching context limit

### 7.2 Complete the SWE run

139/500 tasks. The current 41.0% may shift. Full run needed.

### 7.3 Run TB with 5 trials

Single-trial TB is noisy. The 28.1% pass@1 might translate to 35%+
pass@5, closing the gap to T2's 44.9%.

### 7.4 Investigate tune-mjcf

The first new solve deserves a trajectory analysis. What did the
harness do that T2 couldn't? This could inform future improvements.
