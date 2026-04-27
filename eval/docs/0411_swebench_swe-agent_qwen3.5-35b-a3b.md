# SWE-Bench Verified — swe-agent + Qwen3.5-35B-A3B

**Run**: `jobs_swe_swe-agent_qwen3.5-35b-a3b/2026-04-11__18-55-05`
**Agent**: `swe-agent` (harbor built-in, wraps SWE-agent v1.1.0)
**Model**: `openai/qwen3.5-35b-a3b` (local sglang)
**Dataset**: `swebench-verified`, 100 tasks, n_concurrent=10
**Decoding**: temperature=0.5, max_tokens=8192
**Wallclock**: 2026-04-11 18:55 → 19:17 (≈ 22 min — ~11 s per trial)

## Accuracy

| Metric | Value |
|---|---|
| Pass@1 (100 tasks) | **1 / 100 = 1.0 %** |
| Trials with reward | 97 |
| Trials with errors | 3 (AgentSetupTimeoutError) |

The single pass is noise — the agent crashed before making any edits, and the
autosubmission of an empty patch happened to pass one verifier by chance.

## Token usage

Token counts reported as 0 — swe-agent crashed before accumulating usage.

## Error analysis

**Root cause: litellm cost-limit safety check.** SWE-agent v1.1.0 calls litellm
for cost tracking. Because `openai/qwen3.5-35b-a3b` is not in litellm's price
map, it throws `ModelConfigurationError`:

```
Error calculating cost: This model isn't mapped yet.
model=openai/qwen3.5-35b-a3b, custom_llm_provider=openai.
...please make sure you set `per_instance_cost_limit` and
`total_cost_limit` to 0 to disable this safety check.
```

The agent also warns:

```
Model openai/qwen3.5-35b-a3b does not support function calling.
```

The combination causes swe-agent to error out after sending **one** prompt to
the model, then auto-submit an empty patch — execution takes ~11 s per trial.

## Fix

Pass these agent kwargs to disable the cost guard:

```bash
--agent-kwarg per_instance_cost_limit=0 \
--agent-kwarg total_cost_limit=0 \
--agent-kwarg model.model_kwargs.parse_function=thought_action
```

The `parse_function=thought_action` switches from function-calling to
text-based action parsing, which is required for models that don't support
tool-use natively.

## Recommendation

Re-run with the above kwargs. Without them the agent never actually attempts
the task. Also set a realistic timeout multiplier — once the cost guard is
disabled the agent should run for the full budget.
