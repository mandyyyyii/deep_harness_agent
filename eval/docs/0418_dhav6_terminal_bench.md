# DHAv6 on Terminal-Bench 2.0 (Qwen3.5-35B-A3B)

**Date:** 2026-04-18 (experiment ran 2026-04-17)
**Model:** qwen3.5-35b-a3b
**Benchmark:** terminal-bench v2.0, 89 tasks, 1 trial/task
**Baseline:** Terminus-2 bare (results/terminal_0412, 5 trials/task)
**Prior:** DHAv5 (results/dhav5_tb_0416, 1 trial/task)
**Changes from DHAv5:** Agent-agnostic adapter, L2 validator enabled
(max_tokens=4096), curator prompt with summarize/drop/unresolved schema,
curator passthrough for short conversations

---

## 1. Headline Numbers

| Metric | T2 pass@5 | T2 first-trial | DHAv5 | **DHAv6** |
|--------|----------|---------------|-------|-----------|
| Pass rate | 40/89 (44.9%) | 29/89 (32.6%) | 23/88 (26.1%) | **22/89 (24.7%)** |

DHAv6 is slightly below DHAv5 and 8 points below T2 first-trial.

### Task-level vs T2 pass@5

| Category | Count |
|----------|-------|
| Both pass | 22 |
| DHAv6 only (new solves) | **0** |
| T2 only (regressions) | 18 |

Every task DHAv6 passes, T2 already solves. Zero new solves.

### DHAv6 vs DHAv5

| | Count | Tasks |
|--|-------|-------|
| DHAv6 gains | 8 | bn-fit-modify, build-pmars, constraints-scheduling, count-dataset-tokens, largest-eigenval, log-summary-date-ranges, openssl-selfsigned-cert, sqlite-with-gcov |
| DHAv6 losses | 9 | build-pov-ray, code-from-image, crack-7z-hash, fix-code-vulnerability, headless-terminal, hf-model-inference, merge-diff-arc-agi-task, multi-source-data-merger, pypi-server |
| Net | −1 | |

The 8 gains are exactly the DHAv5 regressions from the 0416 report
(5 of 6 recovered, plus 3 new). These were tasks where DHAv5's
aggressive summarization lost precision — the curator prompt changes
(KEEP-biased, unresolved index) fixed them.

The 9 losses are new regressions, mostly from L2 validator overhead
and over-rejection.

---

## 2. Token Efficiency

| Metric | T2 | DHAv5 | DHAv6 |
|--------|-----|-------|-------|
| Per-turn input | 51.7K | 11.9K | 15.5K |
| Total input (89 tasks) | 203.4M | — | 46.9M |
| Total ratio vs T2 | 1.0x | — | **0.23x** |

DHAv6 uses **4.3x fewer total tokens** than T2 (0.23x). Per-turn
tokens are 15.5K vs T2's 51.7K (0.30x).

However, **DHAv6 uses 1.43x MORE tokens than DHAv5** (per-turn:
15.5K vs 11.9K). The L2 validator accounts for the increase.

---

## 3. Harness Overhead

| Component | Mean tokens | % of generator |
|-----------|-------------|---------------|
| Generator | 552K | 100% |
| Curator | 667K | 121% |
| Validator | 383K | 69% |
| **Total overhead** | **1,050K** | **190%** |

**Overhead ratio: 1.64x** (median 1.50x).

Compared to DHAv5 (1.48x overhead with L2 disabled), DHAv6 is
higher at 1.64x because L2 now works and consumes tokens. The
validator accounts for 383K tokens/task on average.

### Curator stats

| Metric | Value |
|--------|-------|
| Summarize decisions | 46,433 (82.4%) |
| Keep decisions | 9,931 (17.6%) |
| Fallbacks | 39 total |

82.4% summarize rate — down from DHAv5's 93%, reflecting the
KEEP-biased curator prompt. Still high, but the additional KEEP
decisions on precision turns explain the 5/6 DHAv5-regression
recoveries.

### Validator stats

| Metric | Value |
|--------|-------|
| Rule rejects | 761 (32.2% of all validations) |
| **L2 rejects** | **542** |
| L2 passes | 992 |
| L2 skipped (exploration) | 589 |
| L2 fallbacks | 22 |
| **L2 effective reject rate** | **34.8%** |

L2 is functional — 542 rejects, 34.8% reject rate when fired.
This is a dramatic improvement from DHAv5's broken L2 (0 rejects,
1155 fallbacks). The max_tokens=4096 fix resolved the thinking-model
issue.

---

## 4. L2 Validator Analysis

### 4.1 L2 is over-rejecting

| Group | Tasks | Pass rate | Mean overhead |
|-------|-------|-----------|---------------|
| Low L2 (0-4 rejects) | 54 | 31.5% | 1.22x |
| High L2 (5+ rejects) | 35 | 14.3% | 2.28x |

Tasks with heavy L2 activity have half the pass rate and nearly
double the overhead. While correlation ≠ causation (harder tasks
naturally trigger more L2), the overhead cost is clear.

### 4.2 L2 rejects on tasks T2 solves easily

| Task | T2 pass rate | DHAv6 L2 rejects | DHAv6 outcome |
|------|-------------|------------------|---------------|
| code-from-image | 100% | 19 | timeout |
| headless-terminal | 100% | 16 | timeout |
| hf-model-inference | 100% | 4 | timeout |

These are tasks T2 solves 100% of the time. DHAv6 fails them —
partly because L2 is rejecting valid edit commands, forcing the
agent to re-explain and retry. Each L2 rejection costs:
- The L2 LLM call latency (~2-5s)
- The wasted generator turn (agent must propose again)
- The L2 call for the re-proposed command

On headless-terminal: 16 L2 rejects + 8 L2 passes = 24 L2 calls.
With overhead ratio 3.01x, the validator consumed more tokens than
the generator. On code-from-image: 19 rejects + 16 passes, overhead
3.31x.

### 4.3 L2 helps on some tasks

The 8 gains over DHAv5 include tasks where L2 actively rejected:
- bn-fit-modify: 16 L2 rejects (now passes)
- count-dataset-tokens: 6 L2 rejects (now passes)
- largest-eigenval: 7 L2 rejects (now passes)

These suggest L2 is catching shallow edits on some tasks and
steering the agent toward deeper fixes. But the net effect is
negative because the cost (latency + token overhead + false
rejects on easy tasks) outweighs the benefit.

---

## 5. Regression Analysis

### 5.1 Robust regressions (T2 ≥60% pass rate) — 10 tasks

| Task | T2 rate | D6 turns | Overhead | L2 rej | Failure |
|------|---------|---------|----------|--------|---------|
| code-from-image | 5/5 | 35 | 3.31x | 19 | timeout |
| headless-terminal | 5/5 | 37 | 3.01x | 16 | timeout |
| hf-model-inference | 5/5 | 37 | 3.55x | 4 | timeout |
| multi-source-data-merger | 5/5 | 10 | 0.43x | 0 | wrong answer |
| rstan-to-pystan | 5/5 | 59 | 1.73x | 7 | timeout |
| compile-compcert | 4/5 | 80 | 1.47x | 5 | timeout |
| crack-7z-hash | 4/5 | 40 | 1.40x | 2 | timeout |
| fix-code-vulnerability | 4/5 | 31 | 2.09x | 7 | wrong answer |
| pypi-server | 4/5 | 11 | 0.81x | 1 | wrong answer |
| merge-diff-arc-agi-task | 3/5 | 19 | 1.22x | 0 | timeout |

**7 of 10 are timeouts.** The overhead (curator + L2) consumes
wall-clock time that T2 spends on productive turns.

**3 are wrong answers** (multi-source-data-merger, fix-code-vulnerability,
pypi-server) with low overhead — these are likely sampling variance
or curator summarization loss.

### 5.2 Fragile regressions (T2 <60% pass rate) — 8 tasks

| Task | T2 rate | Failure |
|------|---------|---------|
| extract-elf | 2/5 | timeout |
| pytorch-model-cli | 2/5 | wrong answer |
| build-pov-ray | 1/5 | context overflow (257 turns!) |
| custom-memory-heap-crash | 1/5 | timeout |
| fix-ocaml-gc | 1/5 | timeout |
| regex-log | 1/5 | timeout |
| sanitize-git-repo | 1/5 | wrong answer |
| sqlite-db-truncate | 1/5 | timeout |

These are within T2's own sampling variance (T2 fails them 60-80%
of the time). build-pov-ray is notable: 257 turns with 50 L2
rejects — the agent got stuck in a loop that neither the rule
layer nor L2 could break.

---

## 6. DHAv5 Regression Recovery

DHAv5's 0416 report identified 6 regressions where DHAv5 failed
tasks T2 passes. DHAv6 recovers 5 of 6:

| Task | DHAv5 | DHAv6 | T2 rate | What changed |
|------|-------|-------|---------|-------------|
| build-pmars | fail (timeout) | **pass** | 5/5 | KEEP-biased curator preserved build output |
| constraints-scheduling | fail (setup) | **pass** | 2/5 | Infra fix |
| count-dataset-tokens | fail (wrong) | **pass** | 1/5 | L2 caught shallow answer; curator preserved counts |
| log-summary-date-ranges | fail (wrong) | **pass** | 4/5 | Curator passthrough (8 turns, short history) |
| openssl-selfsigned-cert | fail (wrong) | **pass** | 3/5 | Curator passthrough (6 turns) |
| pytorch-model-cli | fail (wrong) | fail (wrong) | 2/5 | Still wrong; L2 rejected 4 times but not enough |

The KEEP-biased curator prompt and the passthrough threshold
directly address the precision-loss failure mode from DHAv5. The
short tasks (log-summary, openssl) benefit from passthrough — zero
curator overhead, full history preserved.

---

## 7. What's Working

1. **Token efficiency vs T2**: 4.3x fewer total tokens. Per-turn
   tokens capped at ~15K instead of growing to 50K+.

2. **Curator KEEP-bias**: 82.4% summarize (down from 93%) preserves
   more precision. Recovered 5 of 6 DHAv5 regressions.

3. **Curator passthrough**: Tasks under 10 turns / 40K chars skip
   the LLM entirely. log-summary-date-ranges and
   openssl-selfsigned-cert pass because of this.

4. **L2 validator works**: 542 rejects, 34.8% reject rate. The
   max_tokens=4096 fix resolved the thinking-model issue completely
   (22 fallbacks, down from 1155).

5. **Rule validator**: 761 rejects, catching duplicates/cycles for
   free.

## 8. What's Not Working

1. **L2 over-rejection on easy tasks**: Tasks T2 solves 100% of the
   time (code-from-image, headless-terminal) get 16-19 L2 rejects,
   consuming turns and wall-clock time. L2's reject rate of 34.8%
   is too high — it should be catching shallow patches, not blocking
   routine edits.

2. **Overhead is higher than DHAv5**: 1.64x vs 1.48x. The L2
   validator adds 69% of generator tokens. On tasks where L2 doesn't
   help, this is pure cost.

3. **Net pass rate hasn't improved**: 24.7% vs 26.1% (DHAv5) vs
   32.6% (T2 first-trial). The curator fixes and L2 gains are
   offset by L2 regressions and overhead timeouts.

4. **Zero new solves**: Every DHAv6 pass is a task T2 already solves.
   The harness hasn't unlocked any task that's beyond the bare agent.

---

## 9. Recommendations

### 9.1 Raise the L2 PASS bar

L2's 34.8% reject rate is too aggressive. The prompt says "default
to PASS" but the model rejects 1 in 3 edits. Options:
- Add explicit examples of valid edits that should PASS
- Require stronger evidence for REJECT (e.g., quote from history
  that contradicts the approach)
- Increase the mitigating-factor list

### 9.2 Skip L2 on short tasks

Tasks under 15 turns rarely benefit from L2 (the agent hasn't had
time to go wrong yet). Add a turn threshold: skip L2 if episode < N.

### 9.3 Run 5 trials

Single-trial comparison is noisy. DHAv6's true pass@5 could be
higher — the 8 DHAv5-regression recoveries suggest the changes
are directionally correct. 5 trials would separate signal from
variance.

### 9.4 Measure L2 precision

Log each L2 rejection reason and the subsequent agent action. If
the agent's next attempt is similar and passes L2, the first
rejection was a false positive. This would quantify L2 precision
and guide prompt tuning.

---

## 10. Summary

| | T2 (first) | DHAv5 | DHAv6 | Δ v5→v6 |
|--|-----------|-------|-------|---------|
| Pass rate | 32.6% | 26.1% | 24.7% | −1.4pp |
| Per-turn tokens | 51.7K | 11.9K | 15.5K | +3.6K |
| Total tokens | 203.4M | — | 46.9M | — |
| Overhead ratio | — | 1.48x | 1.64x | +0.16 |
| L2 rejects | — | 0 (broken) | 542 | fixed |
| Curator summarize rate | — | 93% | 82.4% | −10.6pp |
| DHAv5 regressions recovered | — | — | 5/6 | — |
| New regressions | — | — | 9 (L2 overhead) | — |

**Bottom line:** DHAv6 fixes the two problems identified in DHAv5
(over-summarization and broken L2). Curator KEEP-bias recovers 5/6
DHAv5 regressions. L2 validator works and catches shallow patches.
But L2 over-rejects on easy tasks, and the combined overhead
(1.64x) causes timeout regressions that offset the gains. Net
result: −1 task vs DHAv5, −7 vs T2 first-trial. The machinery
works; the L2 rejection threshold needs tuning.
