# DHAv6 — Agent-Agnostic Deep Harness

## Architecture

```
  ┌──────────────────────────┐
  │     Harbor Framework     │
  │  (setup, env, trajectory)│
  └──────────┬───────────────┘
             │
  ┌──────────▼────────────��──┐
  │    DHAv6 Agent Class     │  dhav6_agent.py or dhav6_miniswe_agent.py
  │  (config, wiring)        │  — thin harbor glue
  └───────��──┬───────────────┘
             │
  ┌──────────���───────────────┐
  │    Harness Loop          │  harness.py — agent-agnostic
  │  (curator, validator,    │
  │   raw.jsonl, trajectory) │
  └───���──────┬────────────���──┘
             │  calls
  ┌──────────▼─────���─────────┐
  │    Agent Adapter         │  adapter.py — ABC
  │  (LLM call, execution,  │
  │   observation formatting)│
  └──────────┬───────────────┘
             │  implements
  ┌──────────▼───────────────┐
  │  Terminus-2 Adapter      │  terminus2_adapter.py
  │  Mini-SWE Adapter        │  miniswe_adapter.py
  └──────────────────────────┘
```

## End-to-End Flow

### Per-episode flow (harness.py)

```
for episode in range(max_episodes):

  1. ALIVE CHECK
     adapter.is_alive() → break if dead

  2. INPUT CURATION (if enabled, episode ≥ 1)
     Read full raw.jsonl from disk
     ├─ If < 10 turns AND < 40K chars → passthrough (no LLM)
     └─ Else → call curator LLM:
          Input:  task, turn, history (reasoning/action/observation per turn),
                  last_observation, total_tokens, budget
          Output: {"summarize": [...], "drop": [...],
                   "unresolved": [...], "curated_last_observation": "..."}
     Rebuild chat._messages:
       [task prompt]
       [unresolved index]  ← top-of-context visibility
       [turn 0: kept / summarized / dropped]
       [turn 1: kept / summarized / dropped]
       ...
     Set prompt = curated_last_observation

  3. LLM CALL
     adapter.call_llm(prompt) → TurnResult
       .raw_commands      — opaque, passed back to execute()
       .command_strings    — plain text for validator
       .is_complete        — task completion flag
       .feedback           — parse errors/warnings
       .agent_reasoning    — full LLM content (for validator L2 + raw.jsonl)
       .reasoning_content  — chain-of-thought (for trajectory)

  4. PARSE ERROR → retry
     If feedback contains "ERROR:":
       Set prompt = error message
       Append to raw.jsonl + trajectory
       continue

  5. OUTPUT VALIDATION (if enabled, has commands)
     Layer 1: Rules (always, free, pure Python)
       ├─ empty check
       ├─ duplicate in last N turns (failed + no state change)
       ├─ cyclic pattern (A-B-A-B)
       └─ syntax (shlex)
       → reject? return templated message, continue
     Layer 2: LLM task-understanding (if enabled)
       Gate: is_edit_or_submission()?
       ├─ whitelisted simple commands (ls, grep, cat...) → skip, PASS
       └─ everything else → call L2 LLM
           Input:  full raw.jsonl, task, agent_reasoning, proposed_command
           Output: {"decision", "category", "concern", "evidence", "suggestion"}
           Reject requires: concern + evidence + suggestion (category optional)
       → reject? return grounded message, continue

  6. EXECUTE
     adapter.execute(raw_commands) → ExecutionResult
       .observation  — raw output
       .timeout      — whether timed out

  7. RECORD EXECUTION
     validator.record_execution(command_strings, observation)

  8. COMPLETION LOGIC
     If is_complete:
       First time  → adapter.get_completion_confirmation(obs)
       Second time → exit loop (task done)
     Else:
       Reset pending, format observation via adapter

  9. APPEND RAW.JSONL
     {turn, timestamp, action, observation, metadata}

  10. TRAJECTORY STEP
      Step(source="agent", message, reasoning_content, tool_calls,
           observation, metrics)
      dump_trajectory()

  11. prompt = observation → next episode
```

### Data flow between components

```
raw.jsonl (append-only, on disk)
  ├─ Written by: harness (step 9), every turn including rejected/error
  ├─ Read by: curator (step 2), every turn from scratch
  └─ Read by: validator L2 (step 5), on edit/submission commands

chat._messages (in memory)
  ├─ Rebuilt by: curator (step 2), from raw.jsonl + decisions
  ├─ Extended by: adapter.call_llm() (step 3), appends user+assistant
  └─ Read by: LLM via adapter (step 3)

validator._history (in memory)
  ├─ Extended by: record_execution (step 7), after successful execution
  ├─ NOT extended on: rejected commands or parse errors
  └─ Read by: Layer 1 rules (step 5)
```

## Included Adapters

### Terminus-2 (`dhav6_agent.py` + `terminus2_adapter.py`)

Text-based JSON prompting. Executes commands via tmux session.
Double-confirms task completion. Extends `Terminus2` base class.

```
harbor run --agent-import-path dhav6_agent:DHAv6Agent \
  -m openai/model -d terminal-bench@2.0 ...
```

### Mini-SWE-Agent (`dhav6_miniswe_agent.py` + `miniswe_adapter.py`)

OpenAI tool-calling format with a single `bash` tool. System message
injected as `{"role": "system"}` in every LLM call (not stored in
chat history — curator only sees user/assistant pairs). Executes via
`environment.exec()` (each command in a new subprocess, no persistent
shell state). No tmux dependency. Extends `BaseAgent` directly.

```
harbor run --agent-import-path dhav6_miniswe_agent:DHAv6MiniSweAgent \
  -m openai/model -d swe-bench ...
```

## Adding a New Agent

Implement `AgentAdapter` (9 methods):

```python
class MyAdapter(AgentAdapter):
    async def is_alive(self) -> bool: ...
    async def call_llm(self, prompt, ...) -> TurnResult: ...
    async def execute(self, raw_commands) -> ExecutionResult: ...
    def format_observation(self, raw_output) -> str: ...
    def get_completion_confirmation(self, obs) -> str | None: ...
    def get_error_response_hint(self) -> str: ...
    @property
    def chat(self) -> Any: ...       # must have ._messages and .reset_response_chain()
    @property
    def model_name(self) -> str: ...
    @property
    def max_episodes(self) -> int: ...
```

The `chat` property must expose:
- `._messages: list[dict]` — curator rebuilds this from raw.jsonl
- `.reset_response_chain()` — called after rebuild (no-op is fine)
- `.total_input_tokens`, `.total_output_tokens`, `.total_cache_tokens`,
  `.total_cost` — for final context population

Then write a harbor agent class that calls `run_harness_loop()`.

## Files

| File | Role |
|------|------|
| `adapter.py` | `AgentAdapter` ABC + `TurnResult` / `ExecutionResult` |
| `harness.py` | Agent-agnostic turn loop |
| `terminus2_adapter.py` | Terminus-2 adapter |
| `miniswe_adapter.py` | Mini-SWE-Agent adapter (tool-calling + env.exec) |
| `dhav6_agent.py` | Harbor agent: terminus-2 + harness |
| `dhav6_miniswe_agent.py` | Harbor agent: mini-swe + harness |
| `input_curator.py` | LLM curator with passthrough |
| `output_validator.py` | Two-layer validator (rules + LLM L2) |
| `validator_rules.py` | Pure Python rule checks |
| `raw_history.py` | JSONL read/write |
| `token_tracker.py` | Token accounting |
| `utils.py` | Shared utilities |
| `prompts/curator_system.txt` | Curator LLM prompt |
| `prompts/validator_task_understanding.txt` | Validator L2 prompt |

## raw.jsonl

Append-only JSONL written by the harness after each turn. Lives at
`<logs_dir>/raw.jsonl`. Both curator and validator L2 read it.
Rejected turns and parse-error turns are included (with metadata)
so the curator sees the full trajectory. Never modified or trimmed.

Each line:
```json
{"turn": 0, "timestamp": "...", "action": "...", "observation": "...", "metadata": {}}
```

## Input Curator

- **Passthrough** when `<10 turns AND <40K chars` — no LLM call.
- **LLM curation** otherwise:
  - Only lists turns to SUMMARIZE or DROP (keeps are implicit)
  - Extracts unresolved issues into a top-of-context index
  - Curates last_observation (trim noise, preserve errors)
  - Splits raw action into reasoning + action for the LLM

## Output Validator

- **Layer 1** (always on): duplicate, cyclic, syntax checks. Free.
- **Layer 2** (default on): LLM task-understanding check.
  - Gate: whitelisted simple commands skip; edits/builds/unknown trigger.
  - Reject requires 3 evidence fields: concern, evidence, suggestion.
  - Category is informational (can be null).
  - Max 2 L2 rejects per turn (safety cap, though in practice
    validate() is called once per episode).

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `enable_curator` | `true` | Enable input curator |
| `enable_validator` | `true` | Enable output validator |
| `curator.budget` | `50000` | Soft token target |
| `validator.rules.duplicate_window` | `5` | Rule check window |
| `validator.task_understanding.enabled` | `true` | Enable Layer 2 |
| `validator.task_understanding.model` | (harness default) | L2 model |
| `validator.task_understanding.max_tokens` | `4096` | L2 output budget (must cover thinking + response) |

## Known Limitations

- **Validator `_l2_rejects_this_turn` cap is effectively dead code.**
  The harness calls `validate()` once per episode with all commands.
  The cap of 2 L2 rejects per turn can only trigger if validate()
  is called multiple times in one episode, which doesn't happen.
  Kept for safety but never fires.

- **Validator `record_execution` truncates observations to 500 chars**
  but `observation_has_error()` checks full output. Error detection is
  correct, but stored snippets may not contain the actual error text.
  This is by design (keep memory bounded).

- **Terminus-2 adapter calls private methods** (`_handle_llm_interaction`,
  `_execute_commands`, etc.) on the parent agent. These are stable in
  practice but would break if harbor renames them.
