"""Output validator: two-layer design, agent-agnostic.

Layer 1 (rules): always runs, pure Python, free. Catches duplicates,
  cyclic repetition, syntax errors.
Layer 2 (LLM task-understanding): runs only on edits and submissions,
  gated by config flag.

Takes command strings (list[str]), not agent-specific command objects.
"""

import json
import logging
import re
from pathlib import Path

import litellm

from dhav6.raw_history import read_turns
from dhav6.token_tracker import TokenTracker
from dhav6.validator_rules import (
    CommandRecord,
    check_cyclic,
    check_duplicate,
    check_empty,
    check_syntax,
    format_rule_rejection,
    is_edit_or_submission,
    observation_has_error,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

L2_PROMPTS = {
    "tolerant": (_PROMPTS_DIR / "validator_tolerant.txt").read_text(),
    "strict": (_PROMPTS_DIR / "validator_strict.txt").read_text(),
}

L2_PARSE_RETRY_SUFFIX = (
    "\n\nYour last response was not valid JSON. Respond with EXACTLY one JSON object "
    'with keys "decision", "category", "concern", "evidence", "suggestion". '
    "No prose, no markdown fences. Begin with { and end with }."
)

ACTION_TRUNCATE = 1000
OBS_TRUNCATE = 2000


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


class OutputValidator:
    def __init__(
        self,
        token_tracker: TokenTracker,
        duplicate_window: int = 5,
        task_understanding_enabled: bool = True,
        task_understanding_mode: str = "tolerant",
        task_understanding_api_base: str | None = None,
        task_understanding_model: str | None = None,
        task_understanding_max_tokens: int = 4096,
    ):
        self.token_tracker = token_tracker
        self._duplicate_window = duplicate_window
        self._l2_enabled = task_understanding_enabled
        self._l2_mode = task_understanding_mode
        if task_understanding_mode not in L2_PROMPTS:
            raise ValueError(
                f"Unknown validator mode '{task_understanding_mode}'. "
                f"Valid: {list(L2_PROMPTS.keys())}"
            )
        self._l2_api_base = task_understanding_api_base
        self._l2_model = task_understanding_model
        self._l2_max_tokens = task_understanding_max_tokens
        self._history: list[CommandRecord] = []
        self._l2_rejects_this_turn = 0

    def reset_turn_counter(self):
        self._l2_rejects_this_turn = 0

    def record_execution(self, command_strings: list[str], output: str):
        turn = self._history[-1].turn + 1 if self._history else 0
        for ks in command_strings:
            self._history.append(CommandRecord(
                keystrokes=ks,
                observation=output[:500],
                turn=turn,
                has_error=observation_has_error(output),
            ))

    async def validate(
        self,
        command_strings: list[str],
        task_instruction: str,
        turn_number: int,
        raw_jsonl_path: Path | None = None,
        agent_reasoning: str = "",
        is_submission: bool = False,
    ) -> tuple[bool, str | None]:
        if not command_strings:
            return True, None

        # ── LAYER 1: RULE CHECKS ───────────────────────────────
        reject = check_empty(command_strings)
        if reject:
            self.token_tracker.n_validator_rule_rejects += 1
            self.token_tracker.n_validator_rejects += 1
            return False, format_rule_rejection(reject)

        reject = check_duplicate(command_strings, self._history, self._duplicate_window)
        if reject:
            self.token_tracker.n_validator_rule_rejects += 1
            self.token_tracker.n_validator_rejects += 1
            return False, format_rule_rejection(reject)

        reject = check_cyclic(command_strings, self._history, self._duplicate_window)
        if reject:
            self.token_tracker.n_validator_rule_rejects += 1
            self.token_tracker.n_validator_rejects += 1
            return False, format_rule_rejection(reject)

        reject = check_syntax(command_strings)
        if reject:
            self.token_tracker.n_validator_rule_rejects += 1
            self.token_tracker.n_validator_rejects += 1
            return False, format_rule_rejection(reject)

        # ── LAYER 2: LLM TASK-UNDERSTANDING ─────────────────────
        if not self._l2_enabled:
            self.token_tracker.n_validator_passes += 1
            return True, None

        any_edit = is_submission or any(
            is_edit_or_submission(ks) for ks in command_strings
        )
        if not any_edit:
            self.token_tracker.n_validator_l2_skipped += 1
            self.token_tracker.n_validator_passes += 1
            return True, None

        if self._l2_rejects_this_turn >= 2:
            self.token_tracker.n_validator_passes += 1
            return True, None

        return await self._l2_validate(
            command_strings, task_instruction, turn_number,
            raw_jsonl_path, agent_reasoning, is_submission,
        )

    async def _l2_validate(
        self,
        command_strings: list[str],
        task_instruction: str,
        turn_number: int,
        raw_jsonl_path: Path | None,
        agent_reasoning: str,
        is_submission: bool,
    ) -> tuple[bool, str | None]:
        history_for_llm = []
        if raw_jsonl_path:
            for rt in read_turns(raw_jsonl_path):
                history_for_llm.append({
                    "turn": rt.turn,
                    "action": rt.action[:ACTION_TRUNCATE],
                    "observation": rt.observation[:OBS_TRUNCATE],
                })

        validator_input = {
            "task": task_instruction,
            "history": history_for_llm,
            "agent_reasoning": agent_reasoning[:3000],
            "proposed_command": "; ".join(command_strings),
            "is_submission": is_submission,
        }
        user_msg = json.dumps(validator_input, ensure_ascii=False)

        parsed = None
        try:
            content, ptok, ctok = await self._call_l2_llm(user_msg, strict=False)
            self.token_tracker.record("validator", ptok, ctok, step=turn_number)
            parsed = _parse_json(content)
            if parsed is None:
                logger.warning(f"[validator-l2] turn {turn_number}: parse failed, retrying")
        except Exception as e:
            logger.warning(f"[validator-l2] turn {turn_number}: API failed: {e}")
            self.token_tracker.n_validator_l2_fallbacks += 1
            self.token_tracker.n_validator_passes += 1
            return True, None

        if parsed is None:
            try:
                content, ptok, ctok = await self._call_l2_llm(user_msg, strict=True)
                self.token_tracker.record("validator", ptok, ctok, step=turn_number)
                parsed = _parse_json(content)
            except Exception:
                pass

        if parsed is None:
            self.token_tracker.n_validator_l2_fallbacks += 1
            self.token_tracker.n_validator_passes += 1
            return True, None

        decision = str(parsed.get("decision", "PASS")).upper()
        if decision == "REJECT":
            category = parsed.get("category")
            concern = parsed.get("concern")
            evidence = parsed.get("evidence")
            suggestion = parsed.get("suggestion")
            if not all([concern, evidence, suggestion]):
                self.token_tracker.n_validator_l2_fallbacks += 1
                self.token_tracker.n_validator_passes += 1
                return True, None

            self._l2_rejects_this_turn += 1
            self.token_tracker.n_validator_l2_rejects += 1
            self.token_tracker.n_validator_rejects += 1
            prefix = f"[{category}] " if category else ""
            msg = (
                f"{prefix}{concern}\n\n"
                f"Evidence: {evidence}\n\n"
                f"Suggestion: {suggestion}"
            )
            return False, msg
        else:
            self.token_tracker.n_validator_l2_passes += 1
            self.token_tracker.n_validator_passes += 1
            return True, None

    async def _call_l2_llm(
        self, user_content: str, strict: bool = False,
    ) -> tuple[str, int, int]:
        system = L2_PROMPTS[self._l2_mode]
        if strict:
            system = system + L2_PARSE_RETRY_SUFFIX
        response = await litellm.acompletion(
            model=self._l2_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=self._l2_max_tokens,
            api_base=self._l2_api_base,
            api_key="dummy",
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        return content, usage.prompt_tokens, usage.completion_tokens
