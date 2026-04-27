# Harbor Integration

DHAv6 is designed as an **external agent** for the [Harbor](https://github.com/runloop/harbor) evaluation framework. No source modification to harbor is needed.

## How it works

Harbor's `--agent-import-path` flag loads any Python class that implements the agent interface. DHAv6 provides two entry points:

| Agent | Import Path | Benchmark |
|-------|-------------|-----------|
| DHAv6 (Terminus-2 adapter) | `dhav6_agent:DHAv6Agent` | Terminal-Bench 2.0 |
| DHAv6 (Mini-SWE adapter) | `dhav6_miniswe_agent:DHAv6MiniSweAgent` | SWE-bench Verified |

## Setup

Add the `dhav6/` directory to your `PYTHONPATH`:

```bash
export PYTHONPATH=/path/to/deep_harness_agent/dhav6:$PYTHONPATH
```

Then invoke harbor as usual:

```bash
harbor run --agent-import-path dhav6_agent:DHAv6Agent \
  -m openai/qwen3.5-35b-a3b -d terminal-bench@2.0 \
  -o results/my_run -n 4 \
  --ak api_base=http://localhost:8051/v1 \
  --ak temperature=0.6 \
  --ak enable_curator=true \
  --ak enable_validator=true
```

## Agent kwargs

| Kwarg | Type | Default | Description |
|-------|------|---------|-------------|
| `api_base` | str | required | SGLang/OpenAI-compatible endpoint URL |
| `temperature` | float | 0.6 | Sampling temperature |
| `enable_curator` | bool | true | Enable LLM input curator |
| `enable_validator` | bool | true | Enable output validator (L1 rules + L2 LLM) |
| `validator.task_understanding.enabled` | bool | true | Enable L2 LLM validator |
| `validator.task_understanding.mode` | str | "tolerant" | L2 strictness: "tolerant" or "strict" |
| `llm_kwargs` | dict | {} | Extra kwargs passed to litellm (top_p, etc.) |
