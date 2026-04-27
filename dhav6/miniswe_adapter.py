"""Mini-SWE-Agent adapter for the DHAv6 harness.

Uses OpenAI tool-calling format with a single "bash" tool.
Executes commands via environment.exec() (each in a new subprocess).
Maintains a text-based message history compatible with the curator.
"""

import json
import logging
from typing import Any

import litellm

from harbor.environments.base import BaseEnvironment

from dhav6.adapter import AgentAdapter, ExecutionResult, TurnResult

logger = logging.getLogger(__name__)

SYSTEM_MESSAGE = "You are a helpful assistant that can interact with a computer."

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                }
            },
            "required": ["command"],
        },
    },
}

SUBMISSION_SENTINEL = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

OUTPUT_TRUNCATE = 10000


class ChatShim:
    """Minimal chat-like interface for curator compatibility.

    The curator accesses chat._messages and chat.reset_response_chain().
    This shim provides both without a full harbor Chat object.
    """

    def __init__(self):
        self._messages: list[dict] = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cache_tokens: int = 0
        self.total_cost: float = 0.0

    def reset_response_chain(self):
        pass

    @property
    def messages(self) -> list[dict]:
        return self._messages


class MiniSweAdapter(AgentAdapter):

    def __init__(
        self,
        environment: BaseEnvironment,
        api_base: str,
        model: str,
        max_episodes: int = 300,
        temperature: float = 0.6,
        top_p: float = 0.95,
    ):
        self._env = environment
        self._api_base = api_base
        self._model = model
        self._max_episodes_val = max_episodes
        self._temperature = temperature
        self._top_p = top_p
        self._chat_shim = ChatShim()

    @property
    def chat(self) -> ChatShim:
        return self._chat_shim

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def max_episodes(self) -> int:
        return self._max_episodes_val

    async def is_alive(self) -> bool:
        return True

    async def call_llm(
        self,
        prompt: str,
        logging_paths: tuple | None = None,
        original_instruction: str = "",
    ) -> TurnResult:
        messages_for_llm = [{"role": "system", "content": SYSTEM_MESSAGE}]
        messages_for_llm.extend(self._chat_shim._messages)
        messages_for_llm.append({"role": "user", "content": prompt})

        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=messages_for_llm,
                tools=[BASH_TOOL],
                temperature=self._temperature,
                top_p=self._top_p,
                api_base=self._api_base,
                api_key="dummy",
            )
        except Exception as e:
            logger.error(f"[miniswe] LLM call failed: {e}")
            return TurnResult(
                raw_commands=[],
                command_strings=[],
                is_complete=False,
                feedback=f"ERROR: LLM call failed: {e}",
                agent_reasoning="",
                reasoning_content=None,
                message_content="",
            )

        msg = response.choices[0].message
        usage = response.usage
        content = msg.content or ""

        commands = []
        tool_calls_raw = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls_raw:
            try:
                args = json.loads(tc.function.arguments)
                cmd = args.get("command", "")
                if cmd:
                    commands.append(cmd)
            except (json.JSONDecodeError, AttributeError):
                continue

        is_complete = any(SUBMISSION_SENTINEL in cmd for cmd in commands)

        # Update chat shim (text-based for curator compatibility)
        self._chat_shim._messages.append({"role": "user", "content": prompt})
        self._chat_shim._messages.append({"role": "assistant", "content": content})

        prompt_tok = usage.prompt_tokens if usage else 0
        completion_tok = usage.completion_tokens if usage else 0
        cache_tok = getattr(usage, "cache_tokens", 0) or 0
        cost = getattr(usage, "cost", 0.0) or 0.0

        self._chat_shim.total_input_tokens += prompt_tok
        self._chat_shim.total_output_tokens += completion_tok
        self._chat_shim.total_cache_tokens += cache_tok
        self._chat_shim.total_cost += cost

        tool_calls_for_traj = None
        if commands:
            tool_calls_for_traj = [
                {
                    "tool_call_id": f"call_{{ep}}_{{i}}",
                    "function_name": "bash",
                    "arguments": {"command": cmd},
                }
                for i, cmd in enumerate(commands)
            ]

        return TurnResult(
            raw_commands=commands,
            command_strings=commands,
            is_complete=is_complete,
            feedback="",
            agent_reasoning=content,
            reasoning_content=getattr(msg, "reasoning_content", None),
            message_content=content,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            cache_tokens=cache_tok,
            cost_usd=cost,
            tool_calls=tool_calls_for_traj,
        )

    async def execute(self, raw_commands: Any) -> ExecutionResult:
        commands: list[str] = raw_commands
        if not commands:
            return ExecutionResult(observation="")

        outputs = []
        for cmd in commands:
            if SUBMISSION_SENTINEL in cmd:
                outputs.append(SUBMISSION_SENTINEL)
                continue
            try:
                result = await self._env.exec(command=cmd, timeout_sec=120)
                rc = result.return_code
                out = result.stdout or ""
                err = result.stderr or ""
                combined = out + ("\n" + err if err else "")
                output_json = json.dumps(
                    {"returncode": rc, "output": combined[:OUTPUT_TRUNCATE]},
                    ensure_ascii=False,
                )
                outputs.append(output_json)
            except Exception as e:
                outputs.append(json.dumps(
                    {"returncode": -1, "output": f"Execution error: {e}"},
                    ensure_ascii=False,
                ))

        return ExecutionResult(
            observation="\n".join(outputs),
            timeout=False,
        )

    def format_observation(self, raw_output: str) -> str:
        if len(raw_output) <= OUTPUT_TRUNCATE:
            return raw_output
        half = OUTPUT_TRUNCATE // 2
        return raw_output[:half] + f"\n...[TRUNCATED]...\n" + raw_output[-half:]

    def get_completion_confirmation(self, observation: str) -> str | None:
        return None

    def get_error_response_hint(self) -> str:
        return "response with at least one bash tool call"
