# Terminal-Bench 2.0 — claude-code + Qwen3.5-35B-A3B

**Run**: `jobs_terminal_claude-code_qwen3.5-35b-a3b/2026-04-11__10-06-29`
**Agent**: `claude-code` (harbor built-in, shells out to `claude` CLI)
**Model**: `openai/qwen3.5-35b-a3b` (intended — never actually called)
**Dataset**: `terminal-bench@2.0`, 89 tasks, n_concurrent=10
**Wallclock**: 2026-04-11 10:06 → 10:21 (≈ 15 min total — ~1 s per trial)

## Accuracy

| Metric | Value |
|---|---|
| Pass@1 (89 tasks) | **0 / 89 = 0.00 %** |
| Trials with reward | 88 |
| Trials with errors | 1 (AgentSetupTimeoutError) |

## Token usage

All zeros / None. The agent never made an LLM call.

## Error analysis

**Root cause: authentication failure.** The harbor `claude-code` agent launches
the `claude` CLI binary inside the docker container. The CLI immediately returns:

```
"Not logged in · Please run /login"
```

with `error: "authentication_failed"`. Agent execution took **1 second** per
trial — it exited before issuing any model request.

**The `claude-code` harbor agent is incompatible with local openai-compatible
endpoints.** It only works with the Anthropic API via the `claude` CLI, which
requires `ANTHROPIC_API_KEY` or an active login session. Passing
`-m openai/qwen3.5-35b-a3b` sets the model name in the metadata but the CLI
still tries Anthropic auth, fails, and exits.

## Recommendation

Do not use `-a claude-code` with non-Anthropic models. For evaluating local
models with a claude-code-style agent loop, use the **meta-harness**
(`agent:AgentHarness`) or **deep-harness-v3** (`agent:DeepHarnessV3CC`), which
implement the same structured-exploration strategy but route LLM calls through
litellm/openai-compatible endpoints.
