# Terminal-Bench 2.0 — terminus-2 + Qwen3.5-35B-A3B

**Run**: `jobs_terminal_terminus-2_qwen3.5-35b-a3b/2026-04-10__14-34-42`
**Agent**: `terminus-2` (built-in harbor agent)
**Model**: `openai/qwen3.5-35b-a3b` (local sglang on `http://<HOST_IP>:<PORT>/v1`)
**Dataset**: `terminal-bench@2.0`, 89 tasks, n_concurrent=10
**Decoding**: temperature=0.5, max_tokens=8192
**Wallclock**: 2026-04-10 14:34 → 18:29 (≈ 3h 54m)

## Accuracy

| Metric | Value |
|---|---|
| Pass@1 over **all 89 tasks** | **12 / 89 = 13.48 %** |
| Pass@1 over trials whose agent actually completed (48) | 12 / 48 = 25.00 % |
| Trials with reward recorded | 48 |
| Trials with errors (no reward) | 41 |

`mean` reported by harbor (denominator = 89): **0.1348**

## Token usage (sum across 89 trials)

| | Value |
|---|---|
| Input tokens  | 96,260,849 |
| Output tokens |  1,277,562 |
| Cache tokens  |          0 |
| cost_usd      | n/a (local model) |

Per-trial average input ≈ 1.08 M tokens; output ≈ 14.4 K tokens.
Average wallclock per trial ≈ **13.0 min**; total compute ≈ 19.3 trial-hours.

## Count usage

- 89 task trials launched (n=89, k=1, l=89)
- 89 result.json files written
- 48 verifier rewards collected; 12 passed (reward = 1.0), 36 failed (reward = 0.0)
- 41 trials short-circuited before producing a reward (errors below)

## Error breakdown

| Exception type | Count |
|---|---:|
| `RuntimeError` (Docker compose failed for environment) | 39 |
| `AgentTimeoutError` (900 s agent budget exceeded) | 19 |
| (no exception, ran to completion) | 31 |

The majority of failures are **environment-build failures**, not model failures: docker compose for the task sandbox returned non-zero before the agent ever ran. Of the 19 agent timeouts, the agent did launch but didn't finish inside the 15-minute terminus-2 budget.

## Analysis

- **Headline**: 13.5 % overall is in line with what small/medium MoE models typically score on TB2 with the stock terminus-2 harness; the meta-harness reference (Claude Opus 4.6) sits at 76.4 %, terminus-2 + GLM-4.7-Flash sits in the 30s.
- The bigger story is the **infrastructure loss**: 39/89 environments (44 %) failed to build at all on this host, capping the achievable score before the model is even invoked. Re-running with `--force-build` and/or staggering concurrency below 10 could recover those tasks. Looking at the failed task names, the docker pulls and image builds tend to be the large/scientific environments (caffe-cifar-10, compile-compcert, distribution-search, etc.).
- Among trials that **did** reach the agent loop, Qwen3.5-35B-A3B passes 25 %, which is a more honest comparison to other agents in this report.
- Output tokens are very low (avg 14 K / trial) — Qwen3.5 is producing short responses; with max_tokens=8192 it's not the cap that's limiting. Worth checking whether it's giving up early or whether terminus-2's structured-action format is biasing it short.
- Next iteration ideas: re-run only the 39 docker-failed tasks with `--force-build`, raise the agent timeout for the 19 timed-out tasks, and consider a temperature sweep.
