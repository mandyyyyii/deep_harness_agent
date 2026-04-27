# Iteration 03 — Baseline Rerun with New Config & Failure Analysis

## Why rerun the baseline?

The prior baseline run (`jobs_terminal_terminus-2_qwen3.5-35b-a3b/2026-04-10__14-34-42`) produced 12/89 = 13.5% pass rate. Closer inspection revealed that this number is **not a faithful measurement of model capability** — most failures were infrastructure issues, not model reasoning issues.

## Prior baseline failure breakdown

Total: 89 tasks. Outcomes:

| Outcome | Count | % |
|---|---|---|
| Passed | 12 | 13.5% |
| Failed (agent ran, wrong answer) | 19 | 21.3% |
| Agent timeout (ran out of wall time) | 19 | 21.3% |
| **RuntimeError — Docker compose failed** | **39** | **43.8%** |

### The Docker failures

All 39 RuntimeErrors were the same error:
```
Network <task>_default Error Error response from daemon:
all predefined address pools have been fully subnetted
failed to create network <task>_default
```

This is a Docker daemon IPAM pool exhaustion. The baseline was running at `-n 10` concurrent trials on a machine where:
- Docker's default `default-address-pools` config carves /16s into /20 subnets (16 subnets per pool, few pools)
- Concurrent container creation + stale networks from prior runs + a second harbor job (`mini-swe-agent` on swebench at `-n 10`) in parallel saturated the pool
- New task containers failed at network creation time, **before the model ever received a prompt**

### Pass rate on tasks where the agent actually ran

| Metric | Value |
|---|---|
| Tasks where Docker came up | 50 |
| Passed (of those) | 12 |
| **Effective pass rate (docker-up)** | **24.0%** |

So the true baseline pass rate under the prior config was 24%, not 13.5%. The other ~11 percentage points were never measured at all — those trials crashed before the model saw a prompt.

### Comparison to official numbers

The official Qwen3.5 report for terminal-bench is ~40%. Our measured 24% is still below that. Gap analysis:

1. **Wrong sampling config.** The prior baseline used `--agent-kwarg model.model_kwargs.temperature=0.5` via dot-path notation, which `parse_kwargs` treated as a literal dict key `"model.model_kwargs.temperature"` and silently dropped (Terminus2 `__init__` doesn't unpack nested dot paths). The actual temperature sent was **0.7** (Terminus2 default), not 0.5. Also no top_p, top_k, min_p, presence_penalty, or repetition_penalty were set — all defaults. Max tokens was 8192, not unlimited.
2. **Thinking mode unknown.** No explicit `enable_thinking` was passed. Qwen3.5-a3b default chat template may or may not include thinking — unclear whether the prior baseline had it enabled or not.
3. **Docker failures inflated the denominator** — even the "effective" 24% is on a biased sample (tasks that tend to have simpler environment setup succeed in network creation while heavier ones fail).
4. **k=1 attempts.** The prior baseline ran each task exactly once. Pass@1 is strictly lower than pass@5 — the official report may be pass@k.

## Iteration 03 baseline config

This rerun fixes all the known issues:

| Parameter | Prior | New |
|---|---|---|
| Concurrent trials (`-n`) | 10 | **2** (fits in Docker pool with headroom) |
| Attempts per task (`-k`) | 1 | **5** (pass@5 measurement) |
| temperature | 0.7 (default, not 0.5 as intended) | **0.6** |
| top_p | default (1.0) | **0.95** |
| top_k | unset | **20** |
| min_p | unset | **0.0** |
| presence_penalty | unset | **0.0** |
| repetition_penalty | unset | **1.0** |
| max_tokens | 8192 | **unlimited** (SGLang default = model max) |
| enable_thinking | unset | **true** (explicit) |

Command:
```bash
harbor run \
  -a terminus-2 \
  -m openai/qwen3.5-35b-a3b \
  -d terminal-bench@2.0 \
  -o results/baseline_iter03 \
  -n 2 -k 5 -l 89 \
  --ak api_base=http://<HOST_IP>:<PORT>/v1 \
  --ak temperature=0.6 \
  --ak 'llm_kwargs={"top_p":0.95,"presence_penalty":0.0,"extra_body":{"top_k":20,"min_p":0.0,"repetition_penalty":1.0,"chat_template_kwargs":{"enable_thinking":true}}}'
```

### Verified on first request

```json
"optional_params": {
  "temperature": 0.6,
  "top_p": 0.95,
  "presence_penalty": 0.0,
  "extra_body": {
    "top_k": 20,
    "min_p": 0.0,
    "repetition_penalty": 1.0,
    "chat_template_kwargs": {"enable_thinking": true}
  }
}
```

All params active; thinking mode confirmed by `</think>` tokens in model responses.

## Results

*(To be filled after run completes — 89 tasks × 5 attempts = 445 trials, estimated ~6–10 hours at `-n 2`)*

| Metric | Prior baseline | Iter03 baseline |
|---|---|---|
| Total trials | 89 | 445 |
| Docker-up rate | 50/89 = 56% | TBD |
| Pass@1 | 12/89 = 13.5% | TBD |
| Pass@5 | n/a | TBD |
| Effective pass rate (docker-up) | 24.0% | TBD |

## Hypothesis

If the new config produces pass@5 in the 30–40% range on tasks where Docker came up, that matches the reported model capability. If it's still far below 40%, the gap is likely:
- Different model variant (vs. `qwen3.5-35b-a3b` MoE)
- Different terminal-bench version
- Different agent harness (original tb repo uses its own runner)
- Different task timeout budgets

If Docker infra still fails a meaningful fraction of tasks at `-n 2`, the issue is not concurrency but pool config. Next step would be to set `/etc/docker/daemon.json` with a larger `default-address-pools` config (requires sudo access) or coordinate the other harbor runs on the machine to serialize launches.
