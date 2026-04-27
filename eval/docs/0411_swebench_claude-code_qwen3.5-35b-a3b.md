# SWE-Bench Verified — claude-code + Qwen3.5-35B-A3B

**Run**: `jobs_swe_claude-code_qwen3.5-35b-a3b/2026-04-11__19-16-47`
**Agent**: `claude-code` (harbor built-in, shells out to `claude` CLI)
**Model**: `openai/qwen3.5-35b-a3b` (intended — never actually called)
**Dataset**: `swebench-verified`, 100 tasks, n_concurrent=10
**Wallclock**: 2026-04-11 19:17 → 19:39 (≈ 22 min — ~1 s per trial)

## Accuracy

| Metric | Value |
|---|---|
| Pass@1 (100 tasks) | **1 / 100 = 1.0 %** |
| Trials with reward | 99 |
| Trials with errors | 1 (AgentSetupTimeoutError) |

The single pass is noise — the agent exited without making any changes,
and the autosubmission of an empty patch happened to match one verifier.

## Token usage

All zeros / None. Same as the terminal-bench claude-code run.

## Error analysis

Same root cause as the terminal-bench claude-code run: **authentication
failure**. The `claude` CLI inside the docker container is not logged in, exits
in 1 s with `"Not logged in · Please run /login"`. No LLM calls are made.

See `docs/0411_terminal-bench_claude-code_qwen3.5-35b-a3b.md` for full details.

## Recommendation

Do not use `-a claude-code` with non-Anthropic models. It requires the
Anthropic API / `claude` CLI auth.
