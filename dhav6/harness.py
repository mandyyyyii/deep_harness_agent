"""Agent-agnostic harness loop with input curation and output validation.

This module owns the turn loop. The agent-specific parts (LLM call,
command execution, observation formatting) are delegated to an
AgentAdapter. The harness handles: curator, validator, raw.jsonl,
trajectory recording, token tracking.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from harbor.models.trajectories import (
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
)

from dhav6.adapter import AgentAdapter
from dhav6.input_curator import curate_input
from dhav6.output_validator import OutputValidator
from dhav6.raw_history import RawTurn, append_turn, now_iso
from dhav6.token_tracker import TokenTracker

logger = logging.getLogger(__name__)


async def run_harness_loop(
    adapter: AgentAdapter,
    initial_prompt: str,
    original_instruction: str,
    *,
    raw_jsonl_path: Path,
    logging_dir: Path | None,
    trajectory_steps: list[Step],
    dump_trajectory: callable,
    token_tracker: TokenTracker,
    enable_curator: bool = True,
    curator_api_base: str = "",
    curator_model: str = "",
    curator_budget: int = 50000,
    curator_reserved_turns: int = 15,
    enable_validator: bool = True,
    validator: OutputValidator | None = None,
) -> int:
    """Run the agent-agnostic harness loop.

    Returns the number of episodes completed.
    """
    prompt = initial_prompt
    first_user_message = initial_prompt
    pending_completion = False

    for episode in range(adapter.max_episodes):
        if not await adapter.is_alive():
            logger.debug("Session ended, breaking loop")
            break

        # ── INPUT CURATION ──────────────────────────────────────
        if enable_curator and episode >= 1:
            prompt = await curate_input(
                chat=adapter.chat,
                first_user_message=first_user_message,
                raw_jsonl_path=raw_jsonl_path,
                last_observation=prompt,
                turn_number=episode,
                token_tracker=token_tracker,
                api_base=curator_api_base,
                model=curator_model,
                budget=curator_budget,
                reserved_turns=curator_reserved_turns,
            )

        # ── EPISODE LOGGING ─────────────────────────────────────
        logging_paths = None
        if logging_dir:
            ep_dir = logging_dir / f"episode-{episode}"
            ep_dir.mkdir(parents=True, exist_ok=True)
            logging_paths = (
                ep_dir / "debug.json",
                ep_dir / "prompt.txt",
                ep_dir / "response.txt",
            )

        # ── LLM CALL ───────────────────────────────────────────
        turn = await adapter.call_llm(
            prompt, logging_paths, original_instruction,
        )

        token_tracker.record(
            "generator", turn.prompt_tokens, turn.completion_tokens,
            step=episode,
        )

        # ── PARSE ERROR → retry ────────────────────────────────
        if turn.feedback and "ERROR:" in turn.feedback:
            prompt = (
                f"Previous response had parsing errors:\n{turn.feedback}\n\n"
                f"Please fix these issues and provide a proper "
                f"{adapter.get_error_response_hint()}."
            )
            trajectory_steps.append(Step(
                step_id=len(trajectory_steps) + 1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                source="agent",
                model_name=adapter.model_name,
                message=turn.agent_reasoning,
                reasoning_content=turn.reasoning_content,
                observation=Observation(
                    results=[ObservationResult(content=prompt)],
                ),
                metrics=Metrics(
                    prompt_tokens=turn.prompt_tokens,
                    completion_tokens=turn.completion_tokens,
                    cached_tokens=turn.cache_tokens or None,
                    cost_usd=turn.cost_usd or None,
                ),
            ))
            _append_raw(raw_jsonl_path, episode, turn.agent_reasoning,
                        prompt, metadata={"parse_error": True})
            continue

        # ── OUTPUT VALIDATION ───────────────────────────────────
        if enable_validator and validator and turn.command_strings:
            validator.reset_turn_counter()
            should_execute, reject_msg = await validator.validate(
                command_strings=turn.command_strings,
                task_instruction=original_instruction,
                turn_number=episode,
                raw_jsonl_path=raw_jsonl_path,
                agent_reasoning=turn.agent_reasoning,
                is_submission=turn.is_complete,
            )
            if not should_execute:
                logger.info(f"[harness] validator REJECT at episode {episode}")
                prompt = reject_msg or "Previous command was rejected. Try a different approach."
                trajectory_steps.append(Step(
                    step_id=len(trajectory_steps) + 1,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    source="agent",
                    model_name=adapter.model_name,
                    message=turn.message_content,
                    observation=Observation(
                        results=[ObservationResult(
                            content=f"[VALIDATOR REJECT] {prompt}",
                        )],
                    ),
                    metrics=Metrics(
                        prompt_tokens=turn.prompt_tokens,
                        completion_tokens=turn.completion_tokens,
                    ),
                ))
                dump_trajectory()
                cmd_text = "; ".join(turn.command_strings)
                _append_raw(raw_jsonl_path, episode, turn.agent_reasoning,
                            f"[REJECTED] {prompt}",
                            metadata={"rejected": True, "commands": cmd_text})
                continue

        # ── EXECUTE COMMANDS ────────────────────────────────────
        exec_result = await adapter.execute(turn.raw_commands)

        if validator and turn.command_strings:
            validator.record_execution(turn.command_strings, exec_result.observation)

        # ── COMPLETION LOGIC ────────────────────────────────────
        was_pending = pending_completion

        if turn.is_complete:
            if pending_completion:
                observation = exec_result.observation
            else:
                pending_completion = True
                confirm = adapter.get_completion_confirmation(exec_result.observation)
                observation = confirm if confirm else exec_result.observation
        else:
            pending_completion = False
            if turn.feedback and "WARNINGS:" in turn.feedback:
                observation = (
                    f"Previous response had warnings:\n{turn.feedback}\n\n"
                    f"{adapter.format_observation(exec_result.observation)}"
                )
            else:
                observation = adapter.format_observation(exec_result.observation)

        # ── RAW.JSONL ───────────────────────────────────────────
        _append_raw(raw_jsonl_path, episode, turn.agent_reasoning,
                    exec_result.observation)

        # ── TRAJECTORY STEP ─────────────────────────────────────
        tool_calls_list = None
        if turn.tool_calls:
            tool_calls_list = [
                ToolCall(
                    tool_call_id=tc["tool_call_id"].format(ep=episode, i=i),
                    function_name=tc["function_name"],
                    arguments=tc["arguments"],
                )
                for i, tc in enumerate(turn.tool_calls)
            ]
            if turn.is_complete:
                tool_calls_list.append(ToolCall(
                    tool_call_id=f"call_{episode}_task_complete",
                    function_name="mark_task_complete",
                    arguments={},
                ))

        obs_results = [ObservationResult(content=observation)]
        trajectory_steps.append(Step(
            step_id=len(trajectory_steps) + 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="agent",
            model_name=adapter.model_name,
            message=turn.message_content,
            reasoning_content=turn.reasoning_content,
            tool_calls=tool_calls_list,
            observation=Observation(results=obs_results),
            metrics=Metrics(
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
                cached_tokens=turn.cache_tokens or None,
                cost_usd=turn.cost_usd or None,
            ),
        ))
        dump_trajectory()

        if turn.is_complete and was_pending:
            return episode + 1

        prompt = observation

    return adapter.max_episodes


def _append_raw(
    path: Path, episode: int, action: str, observation: str,
    metadata: dict | None = None,
) -> None:
    append_turn(path, RawTurn(
        turn=episode,
        timestamp=now_iso(),
        action=action,
        observation=observation,
        metadata=metadata or {},
    ))
