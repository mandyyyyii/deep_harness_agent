# Validator Ablation Analysis: SWE-bench & Terminal-Bench

## Setup

Three validator modes tested, all with curator DISABLED (full history, no compression):

| Mode | Heuristic rules | LLM validator | Description |
|---|---|---|---|
| **rules-only** | ✓ | ✗ | Duplicate detection only (no LLM call) |
| **tolerant** | ✓ | ✓ (lenient) | LLM checks but defaults to PASS when uncertain |
| **strict** | ✓ | ✓ (aggressive) | LLM actively looks for issues to reject |

**Baseline:** Terminus-2 with no validator at all.

---

## Part 1: SWE-bench Verified

### Headline Results

| Mode | Passed | Total | Rate | vs Baseline (61.7%) |
|---|---|---|---|---|
| **Tolerant** | **231/375** | 375 | **61.6%** | **−0.1%** |
| Rules-only | 227/373 | 373 | 60.9% | −0.8% |
| **Strict** | **212/375** | 375 | **56.5%** | **−5.2%** |
| Baseline T2 | 308/499 | 499 | 61.7% | — |

Note: Validator runs completed 373-375 tasks (hit pytest-5840 crash). Baseline has 499.

### Pass/Fail Outcome Breakdown

| | Rules-only | Tolerant | Strict |
|---|---|---|---|
| Both pass (with baseline) | 200 | 203 | 185 |
| Both fail | 116 | 116 | 117 |
| New wins | 27 | 28 | 27 |
| **Regressions** | **30** | **28** | **46** |
| **Net** | **−3** | **±0** | **−19** |

**Tolerant is the only mode that doesn't lose tasks.** It gains 28 new wins and loses exactly 28 — perfectly neutral. Rules-only loses 3 net. Strict loses 19 net — the aggressive rejections cause a cascade of failures.

### Token Usage by Outcome Category

#### Rules-only
| Category | n | Baseline tok | Rules tok | Savings | Baseline eps | Rules eps |
|---|---|---|---|---|---|---|
| Both pass | 200 | 712K | 913K | **−28%** (costs MORE) | 37 | 40 |
| Both fail | 116 | 2,120K | 3,101K | **−46%** (costs MORE) | 62 | 8,676 |
| New wins | 27 | 2,931K | 2,496K | +15% | 66 | 70 |
| Regressions | 30 | 1,931K | 2,586K | −34% | 64 | 64 |

Rules-only costs MORE tokens in almost every category. The "both fail" category shows 8,676 avg episodes — some tasks entered degenerate loops that the heuristic validator couldn't catch (only exact-duplicate detection, no semantic understanding).

#### Tolerant
| Category | n | Baseline tok | Tolerant tok | Savings | Baseline eps | Tolerant eps |
|---|---|---|---|---|---|---|
| Both pass | 203 | 710K | 732K | **−3%** (roughly same) | 37 | 38 |
| Both fail | 116 | 2,384K | 2,051K | **+14%** (saves) | 64 | 60 |
| New wins | 28 | 1,759K | 1,615K | **+8%** (saves) | 56 | 49 |
| Regressions | 28 | 2,067K | 3,965K | **−92%** (costs much more) | 64 | 51 |

Tolerant is well-balanced:
- **Both-pass:** Nearly identical cost (−3%). The validator stays out of the way on successful tasks.
- **Both-fail:** 14% savings. Catches some wasteful commands, reducing token burn.
- **New wins:** 8% savings + solved the task. The validator steered the agent away from dead ends.
- **Regressions:** 92% MORE tokens + lost the task. When tolerant rejects incorrectly, the agent burns tokens retrying and still fails.

#### Strict
| Category | n | Baseline tok | Strict tok | Savings | Baseline eps | Strict eps |
|---|---|---|---|---|---|---|
| Both pass | 185 | 716K | 667K | **+7%** (modest savings) | 37 | 35 |
| Both fail | 117 | 2,253K | 3,051K | **−35%** (costs MORE) | 62 | 48 |
| New wins | 27 | 2,306K | 1,254K | **+46%** (big savings) | 66 | 53 |
| **Regressions** | **46** | 1,512K | 5,714K | **−278%** (catastrophic) | 54 | 48 |

Strict is a double-edged sword:
- **Both-pass:** 7% savings — the validator actually helps slightly by catching minor waste. Fewer episodes (35 vs 37).
- **New wins:** 46% savings — when strict catches a real problem, it saves massive tokens AND solves the task. Best case of any mode.
- **Regressions:** 278% MORE tokens — catastrophic. 46 regressions (vs 28 for tolerant). The strict validator rejects legitimate commands, the agent burns 5.7M tokens retrying, still fails, and often times out (10 timeouts vs 0 in baseline).

### The Strict Death Spiral

Strict's 46 regressions average 5,714K tokens — 3.8x the baseline cost. The mechanism:

1. Agent proposes a valid edit → strict validator rejects it as "shallow" or "incomplete"
2. Agent rephrases the same edit differently → rejected again
3. Agent tries a completely different approach → rejected as "not addressing the core issue"
4. Loop continues, each rejection adding ~10-30K tokens of validator prompt + response
5. Agent hits timeout after burning 5-6M tokens on what should have been a 1.5M task

This happens on 46 tasks — the strict validator's false positive rate is too high for it to be net-positive.

---

## Part 2: Terminal-Bench

### Headline Results

| Mode | Passed | Total | Rate | vs Baseline pass@1 (30.3%) |
|---|---|---|---|---|
| **Tolerant** | **27/89** | 89 | **30.3%** | **±0%** |
| Strict | 23/89 | 89 | 25.8% | −4.5% |
| Baseline pass@1 | 27/89 | 89 | 30.3% | — |

Note: Baseline pass@1 is computed from first attempt of each task in the k=5 run.

### Pass/Fail Outcome Breakdown

| | Strict | Tolerant |
|---|---|---|
| Both pass | 19 | 22 |
| Both fail | 58 | 57 |
| New wins | 4 | 5 |
| Regressions | 8 | 5 |
| Net | −4 | ±0 |

Tolerant is again perfectly neutral: 5 wins, 5 losses, net zero. Strict loses 4 net.

### Token Usage by Outcome Category

#### Strict on Terminal-Bench
| Category | n | Baseline tok | Strict tok | Savings | Notes |
|---|---|---|---|---|---|
| Both pass | 19 | 194K | 308K | **−59%** | Validator overhead on short tasks |
| Both fail | 58 | 3,354K | 2,660K | **+21%** | Some savings on long failures |
| New wins | 4 | 343K | 771K | **−125%** | Won but cost 2x more |
| Regressions | 8 | 474K | 3,502K | **−639%** | Catastrophic: 7.4x cost AND lost |

The regressions are devastating: 8 tasks that baseline solved in ~474K tokens, strict burned 3,502K tokens (7.4x more) and still failed. 4 of the 8 regressions timed out — the validator's false rejections consumed the entire time budget.

#### Tolerant on Terminal-Bench
| Category | n | Baseline tok | Tolerant tok | Savings | Notes |
|---|---|---|---|---|---|
| Both pass | 22 | 200K | 1,129K | **−465%** | Massive overhead |
| Both fail | 57 | 3,401K | 3,007K | **+12%** | Modest savings |
| New wins | 5 | 409K | 536K | **−31%** | Won but cost 1.3x more |
| Regressions | 5 | 616K | 1,810K | **−194%** | 2.9x cost AND lost |

Even tolerant has significant overhead on Terminal-Bench:
- **Both-pass overhead of −465%** is extreme. TB tasks are short (median 15 turns for passes). The validator makes an LLM call on every tool call, adding 5-10K tokens each. Over 17 episodes, that's 85-170K of validator overhead on tasks that only use 200K for the generator. The validator is 5.6x the generator cost.

---

## Summary Table

### SWE-bench (median 34 turns for passes)

| Metric | Rules-only | Tolerant | Strict |
|---|---|---|---|
| Pass rate | 60.9% | **61.6%** | 56.5% |
| Net tasks vs baseline | −3 | **±0** | −19 |
| Token savings (both-pass) | −28% | −3% | **+7%** |
| Token cost (regressions) | −34% | −92% | **−278%** |
| Verdict | Overhead, no benefit | **Best: neutral + safe** | Dangerous |

### Terminal-Bench (median 15 turns for passes)

| Metric | Strict | Tolerant |
|---|---|---|
| Pass rate | 25.8% | **30.3%** |
| Net tasks vs baseline | −4 | **±0** |
| Token savings (both-pass) | −59% | −465% |
| Verdict | Hurts | **Neutral but expensive** |

---

## Key Findings

### 1. Tolerant is the only safe validator mode

Tolerant achieves ±0 net tasks on both benchmarks — it never makes things worse. It catches some genuine waste (14% token savings on SWE both-fail) without triggering death spirals.

### 2. Strict is destructive

Strict causes 46 regressions on SWE-bench (−19 net) and 8 on TB (−4 net). Each regression costs 3-7x more tokens than baseline because the agent enters a reject-retry loop. The strict validator's false positive rate on legitimate commands makes it net-negative.

### 3. The validator is pure overhead on short tasks

On Terminal-Bench (median 15 turns), even tolerant costs 465% more tokens on passed tasks. The validator LLM call cost per turn (~5-10K tokens) exceeds the generator cost for short tasks. The validator only pays for itself on tasks with 50+ turns.

### 4. Rules-only adds cost without benefit

Rules-only (heuristic duplicate detection only) costs more tokens than baseline across all categories and loses 3 net tasks. The heuristic rules are too narrow to catch meaningful waste, but their infrastructure (tracking command history, checking duplicates) still adds overhead.

### 5. Design recommendation

**Skip the validator entirely for short tasks.** The validator should activate only when:
- The agent has run 30+ turns without progress
- The agent proposes a command it has run 3+ times before (the one rule that works)
- The agent is about to submit without verification

This would eliminate the overhead on short/easy tasks while preserving the genuine catches on long/stuck tasks. The tolerant mode is the only viable LLM validator — strict should never be used.

### 6. Comparison: Curator vs Validator

| Component | SWE-bench impact | TB impact | Token effect | Recommendation |
|---|---|---|---|---|
| **Curator N=50** | −0.4% rate, −35% tokens | −1.8% rate | Saves on long tasks, overhead on short | Use adaptively (>30 turns) |
| **Tolerant validator** | ±0% rate, −3% tokens (pass) | ±0% rate, −465% tokens (pass) | Pure overhead on short tasks | Use only on long/stuck tasks |
| **Strict validator** | −5.2% rate, −278% tokens (regress) | −4.5% rate | Destructive | Never use |

The curator (N=50) is the more effective component — it saves 35% tokens overall with minimal accuracy loss. The validator's best mode (tolerant) is neutral on accuracy but adds significant token overhead, especially on Terminal-Bench. Combining curator + tolerant validator may compound the overhead without compounding the benefit.
