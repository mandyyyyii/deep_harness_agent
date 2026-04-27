"""Agent adapter interface for the DHAv6 harness.

The harness loop is agent-agnostic. Each agent provides an adapter that
handles: LLM calls, response parsing, command execution, completion
logic, and observation formatting. The harness handles: curator,
validator, raw.jsonl, trajectory recording, token tracking.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnResult:
    """Result of one LLM call + parse, returned by the adapter."""

    raw_commands: Any
    """Opaque command objects — passed back to adapter.execute() unchanged."""

    command_strings: list[str]
    """Extracted command text for the validator. One string per command."""

    is_complete: bool
    """Whether the agent declared the task complete this turn."""

    feedback: str
    """Parse errors or warnings. Empty string if none."""

    agent_reasoning: str
    """Full LLM response content (for validator Layer 2 and raw.jsonl)."""

    reasoning_content: str | None
    """Extended thinking / chain-of-thought content, if available."""

    message_content: str
    """Formatted message for trajectory recording (may differ from agent_reasoning)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_tokens: int = 0
    cost_usd: float = 0.0

    tool_calls: list[dict] | None = None
    """Agent-specific tool call format for trajectory recording."""


@dataclass
class ExecutionResult:
    """Result of executing commands, returned by the adapter."""

    observation: str
    """Raw output from execution (terminal text, JSON, etc.)."""

    timeout: bool = False
    """Whether execution timed out."""


class AgentAdapter(ABC):
    """Thin adapter that each agent implements.

    The harness loop calls these methods in order:
    1. is_alive() — check if agent session is still running
    2. call_llm(prompt) — call LLM and parse response
    3. execute(raw_commands) — execute commands in environment
    4. format_observation(raw_output) — truncate/format for next prompt
    5. get_completion_confirmation(obs) — double-confirm task completion
    """

    @abstractmethod
    async def is_alive(self) -> bool:
        """Check if the agent's execution environment is still running."""

    @abstractmethod
    async def call_llm(
        self,
        prompt: str,
        logging_paths: tuple | None = None,
        original_instruction: str = "",
    ) -> TurnResult:
        """Call the agent's LLM and parse the response.

        Must handle retries, context-length errors, and response parsing
        internally. Returns a TurnResult with both opaque commands
        (for execute()) and string commands (for validator).
        """

    @abstractmethod
    async def execute(self, raw_commands: Any) -> ExecutionResult:
        """Execute commands in the agent's environment.

        raw_commands is whatever call_llm() returned in TurnResult.raw_commands.
        The harness treats it as opaque.
        """

    @abstractmethod
    def format_observation(self, raw_output: str) -> str:
        """Truncate/format raw execution output for the next LLM prompt."""

    @abstractmethod
    def get_completion_confirmation(self, observation: str) -> str | None:
        """Return a confirmation prompt for task completion, or None to skip.

        Terminus-2 uses double-confirmation (returns a prompt asking the
        agent to confirm). Agents that don't need this return None.
        """

    @abstractmethod
    def get_error_response_hint(self) -> str:
        """Message appended to parse-error feedback to guide the agent."""

    @property
    @abstractmethod
    def chat(self) -> Any:
        """The Chat object for curator to manipulate _messages."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model name for trajectory recording."""

    @property
    @abstractmethod
    def max_episodes(self) -> int:
        """Maximum number of episodes to run."""
