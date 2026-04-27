# Ablation Token Analysis: Where Does the Curator Actually Save Tokens?

## Key Finding

The curator's 35% aggregate token savings is real but misleading. It comes almost entirely from compressing failed and long-running trajectories. For tasks the model solves quickly (≤30 turns), the curator adds overhead and costs MORE tokens than baseline.

---

## Setup

- **Baseline:** Terminus-2 on SWE-bench Verified, no curator, no validator (308/499 = 61.7%)
- **N=50:** DHAv6 with curator reserved_turns=50, heuristic validator only (306/499 = 61.3%)
- **Comparison:** 499 overlapping tasks, matched by task_name

## Task Outcome Breakdown

| Category | Count | Description |
|---|---|---|
| Both pass | 270 | Both baseline and N=50 solved the task |
| Both fail | 155 | Neither solved it |
| T2 pass → N50 fail | 38 | Baseline solved, N=50 lost it (regressions) |
| T2 fail → N50 pass | 36 | N=50 solved, baseline didn't (improvements) |

N=50 has 36 new wins but 38 regressions — a net loss of 2 tasks (306 vs 308). The pass rate difference (61.3% vs 61.7%) is within noise.

## Token Usage by Outcome Category

| Category | Count | T2 tok/task | N50 tok/task | Savings | T2 avg eps | N50 avg eps |
|---|---|---|---|---|---|---|
| **Both pass** | 270 | 735K | 643K | 12.5% | 37.4 | 37.4 |
| **Both fail** | 155 | 2,392K | 1,370K | **42.7%** | 63.9 | 49.6 |
| T2 pass → N50 fail | 38 | 1,853K | 1,361K | 26.5% | 62.3 | 47.7 |
| T2 fail → N50 pass | 36 | 2,685K | 1,218K | **54.6%** | 69.0 | 50.4 |

### Interpretation

**Both-pass tasks (270):** Only 12.5% savings. These tasks have similar episode counts (37.4 vs 37.4) — the curator barely intervenes because the conversation doesn't grow long enough to trigger aggressive compression. The savings come from the small fraction of longer passing tasks.

**Both-fail tasks (155):** 42.7% savings. Failed tasks run much longer (63.9 episodes baseline vs 49.6 with curator). The curator compresses the bloated history of stuck agents, saving tokens but not solving the task. The curator also causes earlier termination (49.6 vs 63.9 episodes) — either by timeout (curator LLM calls eat wall-clock time) or by the model giving up sooner with compressed context.

**T2 fail → N50 pass (36 new wins):** 54.6% savings AND solved the task. These are the curator's genuine victories — by compressing noisy history, it helped the model focus and solve tasks that the baseline couldn't. Average 69 episodes in baseline (long struggle) vs 50 with curator (shorter, successful).

**T2 pass → N50 fail (38 regressions):** 26.5% savings but LOST the task. The curator compressed too much, dropping context the model needed. These tasks were moderately hard (62 episodes baseline) where the model needed sustained context to succeed.

## Token Savings Distribution for Passed Tasks

For the 270 tasks both systems solved:

| Stat | Value |
|---|---|
| Mean savings | **−31.0%** (N50 costs more on average!) |
| Median savings | **−2.4%** |
| P25 | −61.3% (N50 costs 1.6x more) |
| P75 | +36.2% (N50 saves 36%) |
| Min | −941% (extreme overhead on a very short task) |
| Max | +91.3% (huge savings on a long task) |

The mean of −31% is dominated by short tasks where curator overhead exceeds compression benefit. The median of −2.4% shows the typical passed task sees roughly break-even token usage.

## Savings Breakdown by Trajectory Length (Passed Tasks Only)

| Turn range | Count | T2 tok/task | N50 tok/task | Savings |
|---|---|---|---|---|
| **1-15 turns** | 28 | 71K | 174K | **−145%** (N50 uses 2.5x MORE) |
| **16-30 turns** | 101 | 245K | 363K | **−48%** (N50 uses 1.5x MORE) |
| **31-50 turns** | 80 | 690K | 746K | −8% (roughly same) |
| **51-100 turns** | 58 | 1,662K | 1,195K | **+28%** (N50 saves) |
| **100+ turns** | 3 | 6,752K | 1,047K | **+84%** (huge savings) |

### Why short tasks cost MORE with the curator

For tasks solved in ≤30 turns (129 of 270 passed = 48%):
- The conversation never exceeds 30 turns, so `reserved_turns=50` means NO turns are compressed
- But the curator still makes an LLM call every turn to decide "keep all" — pure overhead
- Each curator call adds ~2-5K prompt tokens (the curator sees the conversation + task)
- Over 15-30 turns, that's 30-150K tokens of curator overhead on a task that only used 71-245K for the generator

### Why long tasks cost LESS with the curator

For tasks solved in 51+ turns (61 of 270 passed = 23%):
- Conversation grows beyond 50 turns, curator starts compressing old turns
- Each compressed turn saves ~10-50K tokens per subsequent generator call (because the old observation is replaced with a short summary)
- The savings compound: compressing turn 10 saves tokens on turns 11, 12, 13, ... all the way to the end
- On a 100-turn task, compressing the first 50 turns saves ~500K-2M cumulative tokens

## The Crossover Point

The curator breaks even at approximately **35-40 turns**. Below that, overhead exceeds savings. Above that, compression savings dominate.

```
Turns:  10    15    20    25    30    35    40    50    70    100
Effect: -150% -100% -60%  -30%  -10%  ≈0%   +10%  +28%  +50%  +85%
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        Curator is pure overhead        Curator saves tokens
```

## Implications

### For SWE-bench (median 34 turns for passed tasks)
- ~48% of passed tasks are below the crossover point → curator overhead
- ~23% are above → curator savings
- Net effect: modest savings on passes, big savings on failures
- Overall: −35% tokens with −0.4% pass rate

### For Terminal-Bench (median 15 turns for passed tasks)
- ~75% of passed tasks are below the crossover → mostly overhead
- Only ~10% are above → curator rarely helps
- The curator would need a much smaller N (≈20-25) to be effective, but that risks the "Sisyphean loop" seen at N=10

### Design recommendation

The curator should be **adaptive**, not fixed-N:
1. **Skip curator entirely** for conversations under 30 turns (no LLM call, zero overhead)
2. **Activate curator** only when conversation exceeds a threshold (e.g., 30-40 turns)
3. **Use N=50** once active — the current best window size

This would eliminate the overhead on short tasks while preserving savings on long ones. Expected result: same ~61% pass rate but with 20-30% token savings even on the passed-task subset.

## Raw Data

### Per-task token comparison (sampled)

Tasks where N=50 saved the most (both passed):
```
Task                                    T2 tokens    N50 tokens    Savings
sympy__sympy-15809                      6,051,294       545,818     91.0%
django__django-13786                    4,922,381       539,233     89.0%
sympy__sympy-20428                      4,032,569       646,277     84.0%
```

Tasks where N=50 cost the most extra (both passed):
```
Task                                    T2 tokens    N50 tokens    Overhead
django__django-16527                       14,498       150,781    -940.0%
matplotlib__matplotlib-25311               18,246       125,893    -590.0%
django__django-12708                       27,813       173,456    -523.0%
```

The worst-overhead tasks are all very short (1-5 turns, 14-28K baseline tokens) where the curator's per-turn LLM call cost (~5-10K tokens) dominates.
