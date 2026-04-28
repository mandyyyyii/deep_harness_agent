"""Input curator: reads full raw history from disk, produces curated prompt via LLM.

Every turn the curator:
1. Reads the full raw.jsonl (append-only, never modified)
2. Builds structured turns for the curator LLM (reasoning, action, observation)
3. Gets summarize/drop decisions + unresolved index from the LLM
4. Rebuilds chat._messages: unresolved at top, then chronological history
   with originals for kept turns, summaries for summarized, gaps for dropped
5. Returns the curated last observation as the next prompt

The curator never modifies raw.jsonl. The raw file is the single source of truth;
the curator re-derives compression from scratch every turn, avoiding compounding
summarization loss.
"""

import json
import logging
import re
from pathlib import Path

import litellm

from dhav6.raw_history import RawTurn, read_turns
from dhav6.token_tracker import TokenTracker

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "curator_system_template.txt"
_TEMPLATE_TEXT = _TEMPLATE_PATH.read_text()

# Fallback: if the non-template prompt exists, use it for backward compat
_STATIC_PATH = Path(__file__).parent / "prompts" / "curator_system.txt"

DEFAULT_RESERVED_TURNS = 15

STRICT_RETRY_SUFFIX = (
    "\n\nYour last response was not valid JSON. Respond with EXACTLY one JSON object "
    'with keys "summarize", "drop", "unresolved", "curated_last_observation". '
    "No prose, no markdown fences. Begin with { and end with }."
)

CHARS_PER_TOKEN = 4

REASONING_TRUNCATE = 800
ACTION_TRUNCATE = 500
OBS_TRUNCATE = 2000
LAST_OBS_TRUNCATE = 8000


def _build_system_prompt(reserved_turns: int) -> str:
    """Build curator system prompt with the reserved_turns value interpolated."""
    return _TEMPLATE_TEXT.format(reserved_turns=reserved_turns)


def _parse_json(content: str) -> dict | None:
    if not content:
        return None
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    fence = re.match(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == "{":
            if start == -1:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(content[start : i + 1])
                except json.JSONDecodeError:
                    start = -1
    return None


def _build_curator_turns(raw_turns: list[RawTurn]) -> list[dict]:
    """Convert raw turns into structured dicts for the curator LLM.

    Splits the raw action into reasoning (agent's analysis/plan text)
    and action (the command that was executed). For agents that put
    everything in one field, reasoning may be empty.
    """
    out = []
    for rt in raw_turns:
        full_action = rt.action
        reasoning = ""
        action = full_action[:ACTION_TRUNCATE]

        try:
            parsed = json.loads(full_action)
            if isinstance(parsed, dict):
                reasoning = parsed.get("analysis", "") or parsed.get("plan", "")
                cmds = parsed.get("commands", [])
                if cmds and isinstance(cmds, list):
                    action = "; ".join(
                        c.get("keystrokes", str(c))[:200] if isinstance(c, dict) else str(c)[:200]
                        for c in cmds[:5]
                    )
        except (json.JSONDecodeError, TypeError):
            pass

        obs = rt.observation[:OBS_TRUNCATE]
        out.append({
            "turn": rt.turn,
            "reasoning": reasoning[:REASONING_TRUNCATE],
            "action": action,
            "observation": obs,
            "tokens": (len(full_action) + len(obs)) // CHARS_PER_TOKEN,
        })
    return out


def _format_unresolved_block(unresolved: list[dict]) -> str:
    """Format the unresolved list into a text block for top-of-context injection."""
    if not unresolved:
        return ""
    lines = ["[UNRESOLVED ISSUES — still active from earlier turns]"]
    for entry in unresolved:
        turn = entry.get("turn", "?")
        summary = entry.get("summary", "")
        if summary:
            lines.append(f"  • (turn {turn}) {summary}")
    lines.append("")
    return "\n".join(lines)


def _rebuild_chat_messages(
    first_user_message: str,
    raw_turns: list[RawTurn],
    summarize_map: dict[int, str],
    drop_set: set[int],
    unresolved: list[dict] | None = None,
) -> list[dict]:
    """Build a fresh chat._messages list from raw history + curator decisions."""
    messages: list[dict] = [{"role": "user", "content": first_user_message}]

    unresolved_block = _format_unresolved_block(unresolved or [])
    if unresolved_block:
        messages.append({"role": "assistant", "content": unresolved_block})
        messages.append({"role": "user", "content": "[acknowledged]"})

    for rt in raw_turns:
        if rt.turn in drop_set:
            continue
        elif rt.turn in summarize_map:
            summary = summarize_map[rt.turn]
            messages.append({"role": "assistant", "content": f"[Summary of turn {rt.turn}]: {summary}"})
            messages.append({"role": "user", "content": "[summarized]"})
        else:
            messages.append({"role": "assistant", "content": rt.action})
            messages.append({"role": "user", "content": rt.observation})

    if len(messages) > 1 and messages[-1]["role"] == "user":
        messages.pop()

    return messages


async def _call_curator_llm(
    user_content: str,
    api_base: str,
    model: str,
    reserved_turns: int,
    strict: bool = False,
) -> tuple[str, int, int]:
    system = _build_system_prompt(reserved_turns)
    if strict:
        system = system + STRICT_RETRY_SUFFIX

    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=16384,
        api_base=api_base,
        api_key="dummy",
    )
    content = response.choices[0].message.content or ""
    usage = response.usage
    return content, usage.prompt_tokens, usage.completion_tokens


async def curate_input(
    chat,
    first_user_message: str,
    raw_jsonl_path: Path,
    last_observation: str,
    turn_number: int,
    token_tracker: TokenTracker,
    api_base: str,
    model: str,
    budget: int = 50000,
    reserved_turns: int = DEFAULT_RESERVED_TURNS,
) -> str:
    """Read full raw history, call curator LLM, rebuild chat._messages.

    Returns curated_last_observation. The caller uses it as the prompt
    for the next generator call. chat._messages is rebuilt in-place.

    reserved_turns: number of most-recent turns the curator must keep
    verbatim. If the total history is <= reserved_turns, the curator
    passthroughs without an LLM call (nothing to compress).
    """
    raw_turns = read_turns(raw_jsonl_path)
    if not raw_turns:
        return last_observation

    # Count actual (non-rejected) turns for the passthrough decision
    actual_turns = [rt for rt in raw_turns if not rt.metadata.get("rejected", False)]
    n_actual = len(actual_turns)

    # Passthrough: skip LLM when actual (non-rejected) turns fit in the keep window
    if n_actual <= reserved_turns:
        chat._messages = _rebuild_chat_messages(
            first_user_message, raw_turns,
            summarize_map={}, drop_set=set(),
        )
        chat.reset_response_chain()
        token_tracker.n_curator_pass += len(raw_turns)
        logger.debug(
            f"[curator] turn {turn_number}: passthrough ({n_actual} actual turns <= {reserved_turns} reserved, {len(raw_turns)} total incl rejected)"
        )
        return last_observation

    history_turns = _build_curator_turns(raw_turns)
    total_chars = sum(len(rt.action) + len(rt.observation) for rt in raw_turns)
    total_tokens = total_chars // CHARS_PER_TOKEN

    curator_input = {
        "task": first_user_message[:1500],
        "turn": turn_number,
        "history": history_turns,
        "last_observation": last_observation[:LAST_OBS_TRUNCATE],
        "total_tokens": total_tokens,
        "budget": budget,
    }
    user_msg = json.dumps(curator_input, ensure_ascii=False)

    # First attempt
    parsed = None
    try:
        content, ptok, ctok = await _call_curator_llm(
            user_msg, api_base, model, reserved_turns, strict=False,
        )
        token_tracker.record("curator", ptok, ctok, step=turn_number)
        parsed = _parse_json(content)
        if parsed is None:
            logger.warning(f"[curator] turn {turn_number}: parse failed first attempt, retrying. raw={content[:200]!r}")
    except Exception as e:
        logger.warning(f"[curator] turn {turn_number}: API call failed: {e}")
        token_tracker.n_curator_fallbacks += 1
        return last_observation

    # Retry with strict prompt
    if parsed is None:
        try:
            content, ptok, ctok = await _call_curator_llm(
                user_msg, api_base, model, reserved_turns, strict=True,
            )
            token_tracker.record("curator", ptok, ctok, step=turn_number)
            parsed = _parse_json(content)
            if parsed is None:
                logger.warning(f"[curator] turn {turn_number}: parse failed on retry, falling back. raw={content[:200]!r}")
        except Exception as e:
            logger.warning(f"[curator] turn {turn_number}: retry API call failed: {e}")

    # Final fallback — passthrough
    if parsed is None:
        token_tracker.n_curator_fallbacks += 1
        return last_observation

    # Parse output: summarize + drop (keeps are implicit)
    summarize_list = parsed.get("summarize", [])
    drop_list = parsed.get("drop", [])

    summarize_map: dict[int, str] = {}
    if isinstance(summarize_list, list):
        for entry in summarize_list:
            if isinstance(entry, dict):
                t = entry.get("turn")
                c = entry.get("content", "")
                if t is not None and c:
                    summarize_map[int(t)] = c

    drop_set: set[int] = set()
    if isinstance(drop_list, list):
        for item in drop_list:
            if isinstance(item, (int, float)):
                drop_set.add(int(item))

    # Extract unresolved list
    unresolved = parsed.get("unresolved", [])
    if not isinstance(unresolved, list):
        unresolved = []

    n_summarizes = len(summarize_map)
    n_drops = len(drop_set)
    n_keeps = len(raw_turns) - n_summarizes - n_drops

    # Rebuild chat._messages
    chat._messages = _rebuild_chat_messages(
        first_user_message, raw_turns, summarize_map, drop_set, unresolved,
    )
    chat.reset_response_chain()

    if n_drops > 0 or n_summarizes > 0:
        logger.debug(
            f"[curator] turn {turn_number}: keep={n_keeps} summarize={n_summarizes} "
            f"drop={n_drops} unresolved={len(unresolved)}"
        )
        token_tracker.n_curator_summarize += n_summarizes
    else:
        token_tracker.n_curator_pass += n_keeps or 1

    # Curated last observation
    curated_obs = parsed.get("curated_last_observation")
    if not isinstance(curated_obs, str) or not curated_obs.strip():
        curated_obs = last_observation

    return curated_obs
