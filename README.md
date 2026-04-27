# Deep Harness Agent v6 (DHAv6)

An LLM-driven agent harness for [Terminal-Bench 2.0](https://github.com/runloop/terminal-bench) and [SWE-bench Verified](https://www.swebench.com) evaluation, built on top of [Harbor](https://github.com/runloop/harbor).

DHAv6 wraps any Harbor-compatible base agent (Terminus-2 for TB, Mini-SWE-Agent for SWE-bench) with two runtime augmentation layers:

1. **Input Curator** — An LLM that reads the full conversation history (`raw.jsonl`) each turn and decides per-turn: KEEP, SUMMARIZE, or DROP. This compresses the agent's context window while preserving critical information (error messages, file paths, test output).

2. **Output Validator** — A two-layer filter on agent actions:
   - **Layer 1 (rules, free):** Catches empty commands, exact duplicates, cyclic patterns (A-B-A-B), and syntax errors.
   - **Layer 2 (LLM, gated):** Reviews edit/submission commands against the task description. Rejection requires `concern + evidence + suggestion` — vague objections are suppressed.

## Quick Start

### 1. Environment Setup

```bash
# Create conda env with harbor + sglang + deps
bash scripts/env/setup_env.sh

# Or install into existing env:
pip install -r requirements.txt
```

### 2. Serve a Model

```bash
# Qwen3.5-35B-A3B on 1 GPU
bash scripts/serve/serve_model.sh Qwen/Qwen3.5-35B-A3B 8051 1

# Qwen3.5-397B-A17B on 8 GPUs
bash scripts/serve/serve_model.sh Qwen/Qwen3.5-397B-A17B 8051 8

# GLM-4.7-Flash on 1 GPU
bash scripts/serve/serve_model.sh THUDM/GLM-4.7-Flash 8060 1

# Verify server is healthy
bash scripts/serve/check_server.sh localhost:8051
```

### 3. Run Baselines (6 agents x 2 benchmarks)

```bash
# All 6 baselines on both Terminal-Bench 2.0 and SWE-bench Verified
bash scripts/baselines/run_baselines.sh 8051 qwen3.5-35b-a3b
```

This runs in sequence: **terminus-2**, **terminus-kira**, **mini-swe-agent**, **swe-agent**, **openhands**, **qwen-coder** on both benchmarks.

### 4. Run DHAv6 (curator + validator enabled)

```bash
# Full run: TB2 (n=20) + SWE-verified (n=50)
bash scripts/dhav6/run_dhav6.sh 8051 qwen3.5-35b-a3b
```

Or run a single benchmark with custom config:

```bash
# Debug: TB2 with 4 concurrent, validator in strict mode
VALIDATOR_MODE=strict N=4 bash scripts/dhav6/run_dhav6_single.sh 8051 tb

# Debug: SWE with 2 concurrent, curator disabled
CURATOR=false N=2 LIMIT=50 bash scripts/dhav6/run_dhav6_single.sh 8051 swe
```

### 5. Analyze Results

```bash
python scripts/dhav6/analyze_results.py results/
```

## Architecture

```
Harbor Framework (env, trajectory, verifier)
    |
DHAv6 Agent Class (config, wiring)          dhav6_agent.py / dhav6_miniswe_agent.py
    |
Harness Loop (curator, validator, raw.jsonl) harness.py
    |
Agent Adapter (LLM call, execution)         adapter.py → terminus2_adapter.py / miniswe_adapter.py
```

### Per-episode flow

```
for episode in range(max_episodes):
  1. ALIVE CHECK — is the environment still running?
  2. INPUT CURATION (if enabled, episode >= 1)
     - Read full raw.jsonl
     - LLM decides KEEP/SUMMARIZE/DROP per turn
     - Rebuild context with unresolved-issues index at top
  3. LLM CALL → get next action
  4. OUTPUT VALIDATION (if enabled)
     - Layer 1: rules (empty, dup, cyclic, syntax)
     - Layer 2: LLM review (gated on edit/submission commands)
     - On reject: inject rejection as next prompt, continue
  5. EXECUTE action in environment
  6. RECORD to raw.jsonl + trajectory
  7. COMPLETION: double-confirm before marking done
```

### Data flow

```
raw.jsonl (append-only, on disk)
  ├── Written by: harness (every turn including rejects/errors)
  ├── Read by: curator (every turn, from scratch)
  └── Read by: validator L2 (on edit/submission commands)
```

## Agent kwargs reference

| Kwarg | Default | Description |
|-------|---------|-------------|
| `api_base` | required | SGLang/OpenAI-compatible endpoint URL |
| `temperature` | 0.6 | Sampling temperature |
| `enable_curator` | true | Enable LLM input curator |
| `enable_validator` | true | Enable output validator |
| `validator.task_understanding.enabled` | true | Enable L2 LLM validator |
| `validator.task_understanding.mode` | "tolerant" | L2 strictness: "tolerant" or "strict" |
| `llm_kwargs` | {} | Extra litellm kwargs (top_p, presence_penalty, etc.) |

## File structure

```
dhav6/
├── dhav6_agent.py              # Harbor entry point for Terminal-Bench
├── dhav6_miniswe_agent.py      # Harbor entry point for SWE-bench
├── harness.py                  # Agent-agnostic per-episode loop
├── adapter.py                  # AgentAdapter ABC
├── terminus2_adapter.py        # Terminus-2 bridge (TB2)
├── miniswe_adapter.py          # Mini-SWE-Agent bridge (SWE-bench)
├── input_curator.py            # LLM curator (KEEP/SUMMARIZE/DROP)
├── output_validator.py         # Two-layer output validator
├── validator_rules.py          # Layer 1 rule-based checks
├── raw_history.py              # Append-only raw.jsonl manager
├── token_tracker.py            # Per-call token accounting
├── utils.py                    # Shared helpers
└── prompts/
    ├── curator_system_template.txt   # Curator system prompt
    ├── curator_system.txt            # Curator prompt (legacy)
    ├── validator_strict.txt          # Strict validator prompt
    ├── validator_tolerant.txt        # Tolerant validator prompt
    └── validator_task_understanding.txt  # Base validator prompt
```

## Iteration Reports

Detailed per-iteration analysis reports are in `eval/docs/`. Key reports:

- `0418_dhav6_terminal_bench.md` — TB2 results and failure analysis
- `0418_dhav6_swe_bench.md` — SWE-bench results
- `0419_dhav6_analysis.md` — Cross-benchmark analysis
- `0421_ablation_curator_window.md` — Curator reserved_turns sweep
- `0424_validator_ablation_analysis.md` — Validator mode comparison
- `handoff_guide.md` — Full architecture and design decisions

## License

MIT
