# Harness Framework Analysis

Study of Claude Code's harness architecture, what it bounds, and how to design a trainable deep-harness agent that generalizes to tool-use benchmarks like GAIA.

---

## 1. What Does the Harness Do, Essentially?

A harness is the **outer loop that sits between the LLM and the environment**. It does not solve tasks itself — it orchestrates the model's interaction with tools and intervenes only to prevent waste.

### The Core Cycle

Every harness implements the same fundamental loop:

```
SYSTEM PROMPT + TASK
       |
       v
  +---------+
  |  MODEL  | <-- conversation history (all prior turns)
  +---------+
       |
       v
  PARSE RESPONSE --> tool calls (commands, file edits, etc.)
       |
       v
  VALIDATE (reject if provably wasteful?)
       |
       v
  EXECUTE (run commands, call tools)
       |
       v
  OBSERVE (capture output, truncate if needed)
       |
       v
  MANAGE CONTEXT (compress/trim if approaching limit?)
       |
       v
  FORMAT NEXT PROMPT (observation becomes next user message)
       |
       v
  LOOP until: task_complete / max_steps / session_dead
```

### What the Harness Controls (and What It Doesn't)

**The harness controls:**
- What system prompt the model sees
- What tool schemas are available
- How tool results are formatted and truncated before feeding back
- When/how to compress conversation history
- Whether to reject a response (loop/duplicate detection)
- When to inject meta-messages (stuck nudges, verification prompts)
- When to stop

**The harness does NOT control:**
- What the model decides to do (which tool to call, what arguments)
- The model's reasoning or planning quality
- The model's ability to recover from errors

### Concrete Comparison

| Aspect | Terminus-2 (base) | Deep-Harness V3 | Claude Code |
|---|---|---|---|
| Tool interface | JSON: analysis + plan + commands | Same (inherits) | Native tool_use blocks |
| Output truncation | 10KB, first/last halves | 15KB, first/last halves | Per-tool limits, KB-based |
| Context management | 3-step LLM summarization | Tiered: trim at 85%, revert at 95% (no LLM call) | LLM summarization at 80% threshold |
| Loop detection | None | 3+ identical commands with no writes between | None (relies on model) |
| Stuck detection | None | 3+ turns with identical output hash | None (relies on model) |
| Duplicate blocking | None | MD5 hash tracking + write-awareness | None |
| Completion confirm | 2-step confirmation | 2-step confirmation (inherited) | Model decides end_turn |
| Env bootstrap | None | Auto-snapshot: pwd, ls, language versions | Rich tool definitions + system prompt |
| System reminders | None | None | Dynamic injection (time, skills, hooks) |
| Permission layer | None | None | Classifier + user confirmation + hooks |
| Prompt caching | None | None | Cache-aware: dynamic content in reminders, not system prompt |

---

## 2. What Are the Input Prompt and Output Response Bounded By?

### Input (What the Model Sees Each Turn)

The model receives a **conversation history** structured as:

```
[system_prompt, user_msg_1, assistant_msg_1, user_msg_2, assistant_msg_2, ...]
```

Each component has specific bounds:

#### System Prompt (fixed across turns)

**Terminus-2 / DHA-V3:**
```
Role: autonomous command-line agent in Docker
Workflow: EXPLORE -> ANALYZE -> IMPLEMENT -> VERIFY -> COMPLETE
Tool schema: JSON with analysis, plan, commands[], task_complete
Rules: no side effects, verify before completing
Template vars: {instruction}, {terminal_state}
```

**Claude Code:**
```
Role: "You are Claude Code, Anthropic's official CLI for Claude."
Tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, etc.
Rules: security, reversibility, output efficiency
Dynamic: system-reminders injected per-turn (time, skills, hooks)
```

#### User Messages (observation each turn)

**DHA-V3**: Terminal output from tmux, truncated to `max_output_bytes` (default 15KB), keeping first and last halves. Format:
```
New Terminal Output:
<stdout/stderr from executed commands>
```

Or intervention messages:
- Loop: "WARNING: Same commands repeated N times..."
- Stuck: "STUCK for N turns. ORIGINAL TASK:\n..."
- Validation reject: "You have run X N times with no changes..."
- Verification: "STOP — VERIFY BEFORE COMPLETING..."
- Hard revert: "FRESH START — context was too large..."
- Parse error: "ERROR: {details}. Provide proper tool calls."

**Claude Code**: Tool results as structured `tool_result` blocks:
```json
{
  "tool_use_id": "...",
  "type": "tool_result",
  "content": "...",
  "is_error": true/false
}
```
Plus system-reminder injections with metadata.

#### History Size Bounds

| | DHA-V3 | Claude Code |
|---|---|---|
| Below threshold | Full history, untouched | Full history, untouched |
| Soft threshold (85% / 80%) | Light trim: drop old verbose messages, keep errors + last 8 | LLM summarization: single API call to compress |
| Hard threshold (95%) | Revert: clear all, reset to system + task + terminal snippet | Circuit breaker after 3 rapid refills |

### Output (What the Model Produces Each Turn)

**DHA-V3** expects JSON:
```json
{
  "analysis": "What has been accomplished? What still needs to be done?",
  "plan": "What commands will you run and why?",
  "commands": [
    {"keystrokes": "ls -la\n", "duration": 0.1},
    {"keystrokes": "python3 solve.py\n", "duration": 5}
  ],
  "task_complete": false
}
```

- `analysis`: free-form reasoning (not fed back, only logged)
- `plan`: free-form planning (not fed back, only logged)
- `commands`: array of keystrokes + wait duration — executed sequentially on tmux
- `task_complete`: boolean flag to end the episode

**Claude Code** uses native tool_use blocks:
```json
{
  "type": "tool_use",
  "id": "toolu_...",
  "name": "Bash",
  "input": {"command": "ls -la", "description": "List files"}
}
```

Multiple tool calls per turn are supported. The model can also produce text blocks (shown to user) alongside tool calls.

### The Key Asymmetry

The harness sees **everything** — the full model output, the full environment output — but the model only sees what the harness **chooses to pass through**. This is where the harness has leverage:

- Truncating 50KB of terminal output to 15KB
- Replacing the entire history with "FRESH START" + current state
- Injecting "you're stuck, try something different" as if it were environment output
- Blocking a command and returning cached previous output instead

---

## 3. Designing a Trainable Deep-Harness Agent

### The Core Idea

Instead of hand-coding intervention rules (loop threshold = 3, stuck threshold = 3, etc.), **train a small model to make harness decisions**. The harness becomes a learned policy.

### Architecture

```
                    +------------------+
                    |  TASK LLM        |  (frozen, e.g. GLM-4.7-Flash)
                    |  (the "worker")  |
                    +--------+---------+
                             |
                        tool calls
                             |
                             v
                    +------------------+
                    |  HARNESS AGENT   |  <-- THIS IS WHAT YOU TRAIN
                    |  (small model)   |
                    +--------+---------+
                             |
                    decides: execute? reject? modify? compress? stop?
                             |
                             v
                    +------------------+
                    |  ENVIRONMENT     |
                    |  (tmux/docker)   |
                    +------------------+
```

### What the Harness Agent Sees (Input)

At each turn, the harness agent receives a **state snapshot**:

```python
harness_state = {
    # Current turn
    "worker_response": {                # What the task LLM just produced
        "analysis": "...",
        "plan": "...",
        "commands": [...],
        "task_complete": bool
    },
    
    # History statistics (NOT full history — keep harness context small)
    "turn_number": 15,
    "total_tokens_used": 45000,
    "context_limit": 128000,
    "context_usage_pct": 0.35,
    
    # Behavioral patterns
    "command_repeat_counts": {"ls -la\n": 3, "cat foo.py\n": 1},
    "last_5_commands": ["...", "...", "...", "...", "..."],
    "turns_since_file_write": 4,
    "turns_since_new_command": 2,
    "terminal_output_hash_unchanged_for": 0,
    
    # Environment state
    "terminal_output_preview": "...(last 2KB)...",
    "terminal_output_bytes": 23000,
    
    # Task context
    "original_task": "...(first 500 chars)...",
    "elapsed_steps": 15,
    "max_steps": 89,
}
```

### What the Harness Agent Decides (Output)

The harness agent produces a **structured action**:

```python
harness_action = {
    "execute": True,              # Run the commands as-is?
    "reject_reason": None,        # If not executing, why? (fed back to worker)
    "modify_commands": None,      # Optional: alter commands before execution
    "inject_message": None,       # Optional: prepend guidance to next prompt
    "compress_history": "none",   # "none" | "light_trim" | "summarize" | "revert"
    "force_stop": False,          # Override task_complete if worker is wrong
    "output_budget_bytes": 15000, # How much terminal output to pass through
}
```

### Training Data

**Source 1: Existing DHA-V3 trajectories (imitation learning)**

Every DHA-V3 run already logs:
- `dha_metrics.json`: counts of rejections, compressions, reverts, loop interventions
- Full trajectory with each turn's commands, outputs, and harness decisions

Convert these into (state, action) pairs where the action is what DHA-V3's rules decided. This gives you a starting policy that matches the hand-coded rules.

**Source 2: Outcome-based filtering (offline RL)**

From a corpus of trajectories on terminal-bench:
- **Successful trajectories**: the harness decisions were good — use as positive examples
- **Failed trajectories where harness intervened**: did the intervention help? Compare with/without.
- **Failed trajectories where harness didn't intervene**: should it have? (e.g., model looped for 20 turns — harness should have intervened earlier)

**Source 3: Counterfactual rollouts**

For each harness decision point in a trajectory:
1. Take the state at that point
2. Try multiple harness actions (execute, reject, compress, etc.)
3. Roll out 5-10 steps with each action
4. Score by: did the worker make progress? did it solve the task?

This gives you (state, action, reward) triples for RL.

### Training Approach

**Phase 1: Supervised (imitation)**
- Train on (state, action) from DHA-V3 rules
- Loss: cross-entropy on action fields
- Goal: match the hand-coded policy

**Phase 2: RL fine-tuning (outcome-based)**
- Reward = task success rate improvement over no-harness baseline
- Penalize: extra API calls from rejections, lost information from compression
- Use PPO or DPO on trajectory-level outcomes

**Phase 3: Online improvement**
- Deploy harness agent
- Log trajectories with outcomes
- Re-train on new data
- Iterate

### Model Size

The harness agent should be **small** — it's making simple classification decisions, not solving tasks. A 1-3B parameter model (or even a fine-tuned classifier) should suffice. The input is structured features, not free-form text. Consider:

- A fine-tuned small LLM (Qwen-2.5-1.5B, Phi-3-mini)
- A simple MLP/transformer classifier on the structured state
- Even a decision tree / gradient-boosted model for the simplest version

---

## 4. Generalizing to GAIA and Other Tool-Use Benchmarks

### What Claude Code Does That Generalizes

Claude Code's harness has several principles that are **task-agnostic**:

#### a) Context Management is Universal

Every long-horizon agent hits context limits. Claude Code's approach:
- Monitor usage percentage (not absolute tokens — adapts to model)
- Summarize via LLM call (preserves semantics)
- Re-attach critical state after compaction (files, plans, tasks)
- Circuit breaker for thrash loops

**For GAIA**: Same problem applies. A GAIA task requiring 20+ tool calls (web search, calculator, file reading) will fill context. The harness should:
- Track context usage
- Summarize completed sub-tasks (not just truncate)
- Re-attach the original question + accumulated findings after compaction

#### b) Post-Compaction State Restoration

Claude Code's most underrated feature: after summarizing, it **re-reads recently accessed files** and **re-attaches plans and task state**. This means the model doesn't lose working memory.

**For GAIA**: After compaction, re-attach:
- The original question
- Accumulated facts/answers from prior tool calls
- The current plan / remaining sub-questions
- Any URLs or file paths discovered

#### c) Tool Result Processing

Claude Code truncates large outputs and formats errors distinctly (`is_error: true`). DHA-V3 keeps first/last halves of output.

**For GAIA**: Web search results, document contents, and API responses can be huge. The harness should:
- Truncate web pages to relevant sections (not just byte limits — consider relevance)
- Format errors clearly so the model knows to retry or try differently
- Cache tool results so duplicate calls return cached output instead of re-executing

#### d) System Reminders as Soft Interventions

Claude Code injects `<system-reminder>` blocks with dynamic context (time, available tools, task state) without modifying the system prompt (preserving prompt cache). This is a lightweight way to steer the model without heavy-handed message replacement.

**For GAIA**: Inject reminders like:
- "You have used 15 of 20 allowed steps. Focus on answering the question."
- "You've gathered the following facts so far: [list]. What's still missing?"
- "The question asks for a specific number/name/date. Make sure your final answer is precise."

### What to Adapt for GAIA Specifically

GAIA differs from terminal-bench in key ways:

| | Terminal-Bench | GAIA |
|---|---|---|
| Environment | Docker + tmux (shell commands) | Web search + code interpreter + file tools |
| Task type | Implement/fix code | Answer questions requiring multi-step reasoning |
| Success metric | Automated test pass | Exact-match answer |
| Key failure mode | Looping on same command | Going down wrong search path, losing track of sub-questions |
| Context pressure | Large terminal output | Large web page content |

#### GAIA-Specific Harness Interventions

**1. Search path tracking**
```python
# Track what the agent has searched for and found
search_history = {
    "queries": ["population of france 2023", "GDP of france 2023"],
    "facts_found": {"population": "68.17 million", "GDP": None},
    "sub_questions_remaining": ["What is the GDP of France in 2023?"]
}
```
When the agent repeats a search query, return cached results. When it drifts, inject: "You still need to find: [remaining sub-questions]."

**2. Answer extraction nudging**

GAIA requires exact-match answers. The harness should:
- Detect when the agent has gathered enough information (heuristic: all sub-questions answered)
- Inject: "You have enough information. Provide your final answer now."
- On final answer, validate format (is it a number? a name? does it match expected type?)

**3. Web content filtering**

Raw web pages are huge. The harness should:
- Strip HTML/boilerplate before passing to the model
- Extract only relevant paragraphs (keyword matching against the question)
- Limit to top-K most relevant chunks

**4. Step budget awareness**

GAIA scoring often correlates with efficiency. The harness should:
- Track step count vs. typical budget
- Escalate urgency in later steps: "You have 3 steps remaining."
- Force answer extraction if budget is nearly exhausted

### Learning from Claude Code's Architecture

The key architectural lessons:

1. **Separate orchestration from reasoning.** The harness handles logistics (context, truncation, caching, retries). The model handles reasoning (what to search, how to interpret results). Don't mix them.

2. **Intervene minimally.** DHA-V3's philosophy: "only intervene when clearly necessary (provably duplicate, provably stuck)." Claude Code similarly relies on the model for most decisions. Heavy-handed intervention (rewriting plans, forcing specific tools) tends to hurt more than help.

3. **Preserve information across context boundaries.** The biggest risk in long-horizon tasks is information loss during compaction. Both Claude Code (re-attaching files, plans, tasks) and DHA-V3 (keeping errors and recent messages during trim) prioritize this. For GAIA, the harness should maintain a running "fact sheet" that survives compaction.

4. **Make the harness decisions trainable.** Hard-coded thresholds (85%, 3 repeats, etc.) are brittle. A learned harness can adapt thresholds per-task and per-model. The training signal is task success rate.

5. **Cache-aware design.** Claude Code puts dynamic content in system-reminders (not the system prompt) to preserve prompt caching. For any harness with API costs, this matters: keep the system prompt stable, put per-turn context in user messages.
