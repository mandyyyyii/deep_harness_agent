# Prompt Structure Analysis: Terminus-2 vs Mini-SWE-Agent

## Key Finding

After turn 20, ~95% of the input prompt is conversation history for both agents. Neither agent injects repo maps, workspace snapshots, or codebase content. The entire input is just the message array sent to litellm, growing linearly with each turn.

---

## Terminus-2 Prompt Structure

```
[
  {"role": "user",      "content": "<system instructions + JSON format spec + task + initial terminal>"},
  {"role": "assistant", "content": "<JSON: analysis, plan, commands>"},
  {"role": "user",      "content": "New Terminal Output:\n<stdout from commands>"},
  {"role": "assistant", "content": "<JSON: analysis, plan, commands>"},
  {"role": "user",      "content": "New Terminal Output:\n..."},
  ...repeat for every turn...
  {"role": "user",      "content": "<latest terminal output>"}
]
```

### Key characteristics

- **No system message.** Role description, JSON format spec, and task instruction are all packed into the first `user` message (~3500 chars).
- **Full history every call.** `chat.chat(prompt)` sends `self._messages + [new user msg]` to litellm. No windowing, no truncation of the message array itself.
- **No tool calling.** Commands are embedded in JSON text within assistant messages. No `tools` parameter sent to litellm.
- **Individual terminal outputs capped** at 10KB by `_limit_output_length()` (keeps first and last halves).
- **Proactive summarization** exists but only fires when free tokens < 8000 (out of ~200K context). Uses a 3-step LLM subagent process (summarize → ask questions → answer questions), then replaces history with a compressed handoff.

### What the first user message contains

```
[Role description: 1 sentence]

[JSON format specification: ~1500 chars]
  - analysis field description
  - plan field description
  - commands array schema (keystrokes + duration)
  - task_complete boolean
  - Keystroke formatting rules (newlines, C-c, C-d)
  - Duration guidance (0.1s fast, 1.0s normal, 10-60s slow)

[Task description: ~500-1500 chars]
  "Task Description: {instruction}"

[Initial terminal state: ~100-300 chars]
  "Current terminal state:\nCurrent Terminal Screen:\nroot@abc123:/app#"
```

### Subsequent user messages

Just terminal output, no framing:
```
New Terminal Output:
root@abc123:/app# ls -la
total 48
drwxr-xr-x 3 root root 4096 Jan  1 00:00 .
-rw-r--r-- 1 root root 1234 Jan  1 00:00 task_file
...
```

Or error feedback:
```
Previous response had parsing errors:
ERROR: Invalid JSON - missing closing brace
Please fix these issues and provide a proper response with valid tool calls.
```

### Growth profile

| Turn | Total chars | Instructions % | History % |
|------|-------------|---------------|-----------|
| 1    | 3,478       | 100%          | 0%        |
| 5    | 12,000      | 29%           | 71%       |
| 10   | 25,000      | 14%           | 86%       |
| 20   | 50,000      | 7%            | 93%       |
| 38   | 98,577      | 3.5%          | 96.5%     |

Each turn adds ~1000-1500 chars: assistant JSON (~500-800) + terminal output (~500-10000, typically 1000-3000).

---

## Mini-SWE-Agent Prompt Structure

```
[
  {"role": "system",    "content": "You are a helpful assistant that can interact with a computer."},
  {"role": "user",      "content": "<issue description + workflow guide + command rules + submission instructions>"},
  {"role": "assistant", "content": null, "tool_calls": [{"function": {"name": "bash", "arguments": "{\"command\": \"...\"}"}}]},
  {"role": "tool",      "tool_call_id": "call_...", "content": "{\"returncode\": 0, \"output\": \"...\"}"},
  {"role": "assistant", "content": null, "tool_calls": [...]},
  {"role": "tool",      "content": "{\"returncode\": 0, \"output\": \"...\"}"},
  ...repeat...
]
```

### Key characteristics

- **Minimal system message** — 62 chars: `"You are a helpful assistant that can interact with a computer."`
- **Native OpenAI tool calling** — single tool `bash` passed via `tools` parameter (not in messages).
- **Full history every call.** `self.messages` accumulates indefinitely. Zero summarization, zero windowing.
- **Individual tool outputs** capped at 10K chars (head 5K + tail 5K if exceeded), formatted as JSON: `{"returncode": N, "output": "..."}`.
- **No summarization mechanism.** If context fills up, mini-swe-agent hits `ContextWindowExceededError` and aborts.

### What the first user message contains

```
[Issue description from SWE-bench: variable length, typically 200-2000 chars]
  "Please solve this issue: {title}\n\nDescription: {body}"

[Workflow guidance: ~1500 chars]
  "## Recommended Workflow
   1. Analyze the codebase by finding and reading relevant files
   2. Create a script to reproduce the issue
   3. Edit the source code to resolve the issue
   4. Verify your fix works
   5. Test edge cases
   6. Submit: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

[Command execution rules: ~1500 chars]
  "## Command Execution Rules
   - Each command runs in a new subshell
   - Directory/env changes are not persistent
   - Response MUST include at least one bash tool call
   - Submit via: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

[System information: ~100 chars]
  "<system_information>Linux 6.8.0 x86_64</system_information>"

[Useful command examples: ~800 chars]
  "### Create a new file: cat <<'EOF' > ..."
  "### Edit files with sed: sed -i 's/old/new/g' ..."
  "### View file content: nl -ba filename.py | sed -n '10,20p'"
```

Total first user message: ~5800 chars.

### Tool schema (sent as `tools` parameter, not in messages)

```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "description": "Execute a bash command",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {
          "type": "string",
          "description": "The bash command to execute"
        }
      },
      "required": ["command"]
    }
  }
}
```

### Assistant messages

Content is `null` or empty. Reasoning/thinking goes into `content` field when thinking mode is on. Actual commands go in `tool_calls`:
```json
{
  "role": "assistant",
  "content": "Let me explore the codebase to understand the issue...",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "bash",
        "arguments": "{\"command\": \"find /testbed -name 'filters.py' | head -10\"}"
      }
    }
  ]
}
```

### Tool result messages

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"returncode\": 0, \"output\": \"/testbed/django/contrib/admin/filters.py\\n/testbed/tests/admin_filters/tests.py\"}"
}
```

### Growth profile

| Turn | Total chars | Instructions % | History % |
|------|-------------|---------------|-----------|
| 1    | 5,843       | 100%          | 0%        |
| 10   | 24,750      | 24%           | 76%       |
| 50   | 87,527      | 7%            | 93%       |
| 100  | 180,343     | 3%            | 97%       |
| 149  | 259,660     | 2%            | 98%       |

Each turn adds ~1600 chars on average: assistant tool_call (~200-800) + tool output (~500-5000, capped at 10K).

---

## Side-by-Side Comparison

| Aspect | Terminus-2 | Mini-SWE-Agent |
|--------|-----------|----------------|
| System message | None (packed into first user msg) | 62 chars ("You are a helpful assistant...") |
| First user message | ~3500 chars (instructions + task + terminal) | ~5800 chars (issue + workflow + rules) |
| Tool interface | JSON text in assistant content | Native OpenAI tool_calls + tool results |
| Tool schema | None (format described in text) | Single `bash` tool via `tools` param |
| History management | Full history; optional 3-step summarization at low-token threshold | Full history; no summarization, aborts on overflow |
| Output truncation | 10KB per terminal output (first/last halves) | 10KB per tool output (first/last 5K) |
| Repo/workspace injection | None | None |
| Per-turn growth | ~1000-1500 chars | ~1600 chars |
| At turn 50 | ~93% history | ~93% history |

---

## What's NOT in the Prompt (for either agent)

Neither agent injects any of the following:

- **Repo map or file tree** — no structural overview of the codebase
- **Workspace state** — no snapshot of modified files, git status, etc.
- **Retrieved documentation** — no RAG, no relevant docs pulled in
- **Dynamic tool schemas** — no tools added or removed based on context
- **Agent memory** — no persistent memory across tasks
- **Codebase embeddings** — no semantic search results

All codebase knowledge enters the context ONLY through the agent's own `cat`, `grep`, `find` commands and their terminal/tool output. This means:
1. The agent must spend turns exploring the codebase (each exploration turn adds to history)
2. File contents seen early get buried deep in history as the context grows
3. Re-reading a file wastes tokens but is sometimes necessary because the model can't attend to content 50K tokens back

---

## Implication for DHAv4 Curator

The curator's job is straightforward: **manage the conversation history**, because that's all there is. Specifically:

1. **Summarize old (action, observation) pairs** — "turns 5-15: explored repo structure, found key files at X, Y, Z. Key finding: the bug is in file A at line N."
2. **Drop redundant file reads** — if the agent `cat`s the same file twice, the second read adds ~5K tokens for zero new information.
3. **Preserve error messages and key findings** — these are the highest-value tokens in the history.
4. **Keep recent turns intact** — the last 5-8 turns are the agent's working memory.

There is no repo map to curate, no injected context to manage, no tool schemas to trim. It's purely about compressing the linear accumulation of (action, observation) pairs.
