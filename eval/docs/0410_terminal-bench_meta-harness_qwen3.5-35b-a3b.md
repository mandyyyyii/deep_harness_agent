# Terminal-Bench 2.0 — meta-harness (KIRA env-bootstrap) + Qwen3.5-35B-A3B

**Run**: `jobs_terminal_meta-harness_qwen3.5-35b-a3b/2026-04-10__18-44-07`
**Agent**: `meta-harness-tbench2-artifact:agent.AgentHarness` (Terminus-KIRA + env-bootstrap)
**Model**: `openai/qwen3.5-35b-a3b` (local sglang on `http://<HOST_IP>:<PORT>/v1`)
**Dataset**: `terminal-bench@2.0`, 89 tasks, n_concurrent=10
**Decoding**: temperature=0.5
**Wallclock**: 2026-04-10 18:44 → 23:31 (≈ 4h 47m)

> Status: **this run was kicked off accidentally** when the original 3-option script
> was already buffered by bash before later edits removed it. Reported here
> because results exist; not part of the user's intended plan.

## Accuracy

| Metric | Value |
|---|---|
| Pass@1 over **all 89 tasks** | **1 / 89 = 1.12 %** |
| Pass@1 over trials with reward (88) | 1 / 88 = 1.14 % |
| Trials with reward recorded | 88 |
| Trials with errors | 89 (every trial logged at least one exception) |

`mean` reported by harbor (denominator = 89): **0.0112**

## Token usage (sum across 89 trials)

| | Value |
|---|---|
| Input tokens  | 877,839,991 |
| Output tokens |   4,115,044 |
| Cache tokens  |           0 |
| cost_usd      | n/a (local model) |

Per-trial average input ≈ 9.86 M tokens; output ≈ 46 K tokens — **9× the input
volume of terminus-2** for essentially zero accuracy. Average wallclock per
trial ≈ **28.1 min**; total compute ≈ 41.8 trial-hours.

## Count usage

- 89 task trials launched (n=89, k=1, l=89)
- 89 result.json files written
- 88 verifier rewards collected; 1 passed (reward = 1.0), 87 failed
- Every trial logged an exception

## Error breakdown

| Exception type | Count |
|---|---:|
| `AgentTimeoutError` (900 s agent budget exceeded) | 88 |
| `OutputLengthExceededError` | 1 |

## Analysis

- **The harness collapsed.** 88/89 trials hit the 900-second agent timeout. The
  one passing trial is essentially noise.
- Cause is almost certainly a **harness/model mismatch**: the meta-harness was
  tuned for Claude Opus 4.6, where its structured exploration + env bootstrap
  pays off in a small number of fast turns. With Qwen3.5-35B-A3B, the rollouts
  spend the 15-minute budget without converging — the high input-token total
  (~10 M / trial vs ~1 M for terminus-2) suggests the model is doing many short
  tool-call cycles inside an ever-growing context, and never reaches a final
  answer before the timeout fires.
- Concretely: 9.86 M input tokens / trial means hundreds of LLM calls per
  trial against a context that keeps re-feeding the bootstrap snapshot. Either
  the timeout needs to be raised dramatically (probably impractical) or the
  harness needs Qwen-specific tuning (smaller context window, fewer tool
  layers, different stopping criteria).
- **Recommendation**: do not use meta-harness with non-Claude models without
  reworking the loop. terminus-2 is the better baseline for Qwen3.5 on TB2.
- Cost to the cluster: ~42 trial-hours of GPU time for ~1 % accuracy. Worth
  checkpointing and aborting the run if `mean` stays under 0.05 after the
  first dozen trials in future.
