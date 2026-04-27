"""Terminus-2 adapter for the DHAv6 harness."""

from typing import Any

from harbor.agents.terminus_2.terminus_2 import Command
from harbor.agents.terminus_2.tmux_session import TmuxSession
from harbor.llms.chat import Chat
from harbor.models.trajectories import ToolCall

from dhav6.adapter import AgentAdapter, ExecutionResult, TurnResult


class Terminus2Adapter(AgentAdapter):
    """Wraps a Terminus2 agent instance for the harness loop."""

    def __init__(self, agent, chat: Chat, session: TmuxSession):
        self._agent = agent
        self._chat = chat
        self._session = session

    @property
    def chat(self) -> Chat:
        return self._chat

    @property
    def model_name(self) -> str:
        return self._agent._model_name

    @property
    def max_episodes(self) -> int:
        return self._agent._max_episodes

    async def is_alive(self) -> bool:
        return await self._session.is_session_alive()

    async def call_llm(
        self,
        prompt: str,
        logging_paths: tuple | None = None,
        original_instruction: str = "",
    ) -> TurnResult:
        tokens_before_in = self._chat.total_input_tokens
        tokens_before_out = self._chat.total_output_tokens
        tokens_before_cache = self._chat.total_cache_tokens
        cost_before = self._chat.total_cost

        commands, is_complete, feedback, analysis, plan, llm_response = (
            await self._agent._handle_llm_interaction(
                self._chat,
                prompt,
                logging_paths or (None, None, None),
                original_instruction,
                self._session,
            )
        )

        prompt_tok = self._chat.total_input_tokens - tokens_before_in
        completion_tok = self._chat.total_output_tokens - tokens_before_out
        cache_tok = self._chat.total_cache_tokens - tokens_before_cache
        cost = self._chat.total_cost - cost_before

        if self._agent._save_raw_content_in_trajectory:
            message_content = llm_response.content
        else:
            parts = []
            if analysis:
                parts.append(f"Analysis: {analysis}")
            if plan:
                parts.append(f"Plan: {plan}")
            message_content = "\n".join(parts) if parts else ""

        tool_calls = None
        if not self._agent._save_raw_content_in_trajectory and commands:
            tool_calls = [
                {"tool_call_id": f"call_{{ep}}_{{i}}", "function_name": "bash_command",
                 "arguments": {"keystrokes": cmd.keystrokes, "duration": cmd.duration_sec}}
                for i, cmd in enumerate(commands)
            ]

        return TurnResult(
            raw_commands=commands,
            command_strings=[cmd.keystrokes for cmd in commands],
            is_complete=is_complete,
            feedback=feedback,
            agent_reasoning=llm_response.content,
            reasoning_content=llm_response.reasoning_content,
            message_content=message_content,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            cache_tokens=cache_tok,
            cost_usd=cost,
            tool_calls=tool_calls,
        )

    async def execute(self, raw_commands: Any) -> ExecutionResult:
        commands: list[Command] = raw_commands
        timeout, output = await self._agent._execute_commands(
            commands, self._session,
        )
        return ExecutionResult(observation=output, timeout=timeout)

    def format_observation(self, raw_output: str) -> str:
        return self._agent._limit_output_length(raw_output)

    def get_completion_confirmation(self, observation: str) -> str | None:
        return self._agent._get_completion_confirmation_message(observation)

    def get_error_response_hint(self) -> str:
        return self._agent._get_error_response_type()
