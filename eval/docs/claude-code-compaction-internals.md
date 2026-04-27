# Claude Code Compaction Internals

How Claude Code (v2.1.98) handles context summarization and long-horizon conversations.

Source: minified bundle at `@anthropic-ai/claude-code/cli.js` (line ~4534 in minified output).

---

## Overview

Claude Code uses **LLM-based conversation summarization** to handle long conversations. When context usage approaches a threshold, it makes a separate API call to summarize the conversation history, then replaces old messages with the summary.

## When Compaction Triggers

### Automatic (autocompact)
- Monitors context usage as a percentage of the model's context window
- Triggers when token count crosses the **auto-compact threshold** (configurable via `CLAUDE_CODE_AUTO_COMPACT_WINDOW` or `/autocompact` command)
- Checked after each query in the main agent loop

### Manual
- User invokes `/compact` slash command
- Supports directional compaction: `"up_to"` (summarize everything before a message) or `"from"` (summarize everything after)

## The Summarization Call

The core compaction is a single LLM call — not a multi-step agent process.

### System Prompt

```
"You are a helpful AI assistant tasked with summarizing conversations."
```

That is the entire system prompt for the summarization agent. Nothing else.

### How It Works

1. **Build a summary request message** — constructed by an internal function that includes:
   - The compaction direction (up_to or from)
   - Any custom user instructions or context
   - Note: "There may be additional summarization instructions provided in the included context. If so, remember to follow these instructions when creating the above summary."

2. **Pass the conversation messages** — the messages to be summarized are passed as the input to the LLM call.

3. **Call the model** — uses the same model as the main loop (`mainLoopModel`), with:
   - `thinkingConfig: { type: "disabled" }` — no extended thinking
   - `enablePromptCaching: false`
   - `maxOutputTokensOverride` capped to a limit
   - `querySource: "compact"` for telemetry

4. **Tool use is denied** — the summarizer can only produce text:
   ```
   { behavior: "deny", message: "Tool use is not allowed during compaction" }
   ```

5. **Stream the response** — the summary is streamed back, with progress updates sent to the UI.

### Two Compaction Paths

**Path 1: Cache-sharing (tried first)**
- Attempts compaction via a "forked" call with `skipCacheWrite: true` and `skipTranscript: true`
- Goal: reuse the existing prompt cache from the main conversation for cheaper/faster compaction
- If the response is valid, uses it directly

**Path 2: Streaming fallback**
- If cache sharing fails or returns no valid text, falls back to a full streaming call
- This is the standard path described above

### Retry on Prompt-Too-Long

If the model returns an error indicating the prompt is too long:
- Drops older messages from the input
- Retries up to **3 times**
- If all retries fail: `"Conversation too long. Press esc twice to go up a few messages and try again."`

## Post-Compaction Restoration

After the summary is generated, Claude Code **re-attaches important state** so the model doesn't lose awareness of key context:

1. **File contents** — recently-read files are re-read and attached (up to 5 files, capped at 50k tokens total, each file max 5k tokens)
2. **Plan file** — if a plan exists, it's re-attached
3. **Invoked skills** — recently used skill content is re-attached (max 25k tokens)
4. **Task statuses** — running local agent tasks are re-attached
5. **Agent ID reference** — if running as a subagent, identity is preserved
6. **Hook results** — `PreCompact` and `PostCompact` hooks fire, allowing plugins to inject content to preserve

### Final Message Structure

After compaction, the conversation becomes:
```
[boundary_marker, ...summary_messages, ...messages_to_keep, ...attachments, ...hook_results]
```

Where:
- `boundary_marker` — metadata tracking compaction point, pre-compact token count, discovered tools
- `summary_messages` — the LLM-generated summary (marked with `isCompactSummary: true`)
- `messages_to_keep` — messages after the compaction point (for `up_to` direction)
- `attachments` — restored files, plans, skills, tasks
- `hook_results` — output from PostCompact hooks

## Safety Mechanisms

### Circuit Breaker
- After **3 consecutive compaction failures**, autocompact stops attempting for the rest of the session
- Prevents burning API calls on a conversation that can't be compacted

### Rapid-Refill Breaker
- Tracks how quickly context refills after compaction
- If context refills within a small number of turns **3 consecutive times**, the breaker trips
- Error: stops with an actionable message instead of compacting in an infinite loop

### Abort Handling
- Compaction respects the session's abort controller
- If the user cancels (Esc), compaction is interrupted cleanly

## Configuration

| Setting | Description |
|---|---|
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Override auto-compact window size (tokens) |
| `DISABLE_COMPACT` | Disable auto-compaction entirely |
| `/autocompact [tokens\|reset]` | Configure auto-compact window interactively |
| `/config` → auto-compact toggle | Enable/disable auto-compact |
| `/compact` | Manually trigger compaction |

## Comparison with Deep-Harness Approaches

### vs. Terminus-2 (harbor)
Terminus-2 also uses LLM summarization but with a **3-step process**: (1) generate summary, (2) ask clarifying questions, (3) answer questions. Claude Code uses a simpler single-call approach. Terminus-2 also has a message-unwinding fallback that removes recent message pairs without summarization.

### vs. Deep-Harness V3
V3 uses **no LLM calls** for context management:
- 85% threshold: light trim (drop oldest verbose messages, keep errors + recent)
- 95% threshold: hard revert (reset to system prompt + task + current terminal state)

This is cheaper but loses more information. Claude Code's LLM summarization preserves semantic understanding at the cost of an extra API call per compaction.

### vs. Deep-Harness V2
V2 had a `use_full_history` toggle (P1) for ablation studies. When disabled, it would fall back to terminus-2's summarization. V3 dropped this toggle — always uses full history with its own tiered trimming.
