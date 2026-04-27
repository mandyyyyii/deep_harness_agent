# SWE-Bench Verified — mini-swe-agent + Qwen3.5-35B-A3B

**Run**: `jobs_swe_mini-swe-agent_qwen3.5-35b-a3b/2026-04-11__10-21-24`
**Agent**: `mini-swe-agent` (harbor built-in)
**Model**: `openai/qwen3.5-35b-a3b` (local sglang)
**Dataset**: `swebench-verified`, 100 tasks, n_concurrent=10
**Decoding**: temperature=0.5, max_tokens=8192
**Wallclock**: 2026-04-11 10:21 → 18:55 (≈ 8h 34m)

## Accuracy

| Metric | Value |
|---|---|
| Pass@1 (100 tasks) | **0 / 100 = 0.00 %** |
| Trials with reward | 98 |
| Trials with errors | 100 (98 AgentTimeoutError, 2 AgentSetupTimeoutError) |

## Token usage

Token counts reported as 0 — mini-swe-agent does not populate `n_input_tokens`
/ `n_output_tokens` in the harbor result schema (it tracks tokens internally
but doesn't surface them).

## Count usage

- 100 task trials launched
- 98 agent instances ran to the 3000 s timeout (50 min each)
- 2 failed during agent setup
- 0 patches resolved the underlying issue

## Analysis

Every trial that reached the agent loop ran for exactly **3000 s** (the full
50-minute timeout) and still produced no correct patch. The agent *is*
functioning — it successfully calls the sglang endpoint and generates
responses — but it cannot converge on a working fix within the time budget.

Possible factors:
- **Model capability**: Qwen3.5-35B-A3B (3 B activated) is a very small model
  for SWE-Bench tasks, which require reasoning about large codebases, writing
  multi-file patches, and running test suites.
- **Timeout budget**: 50 min should be sufficient for simple fixes; the model
  appears to be looping or making incremental but non-converging attempts.
- **mini-swe-agent harness**: designed for SWE-Bench but may need tuning for
  smaller / MoE models.

## Recommendation

SWE-Bench Verified is likely out of range for Qwen3.5-35B-A3B at this model
size. Consider trying with a larger model (e.g., Qwen3-30B-A3B or a full
dense 72B) before investing more compute on this agent + model combination.
