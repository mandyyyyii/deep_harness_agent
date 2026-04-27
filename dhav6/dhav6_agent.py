"""
DHAv6 Agent — Agent-agnostic harness with pluggable adapters.

The harness loop (curator + validator + raw.jsonl) lives in harness.py.
This file is the harbor integration that creates the adapter, wires
config, and delegates to the harness.

Usage (with terminus-2 adapter):
    PYTHONPATH=dhav6 harbor run \\
      --agent-import-path dhav6_agent:DHAv6Agent \\
      -m openai/glm-4.7-flash -d terminal-bench@2.0 \\
      -o results/dhav6_iter01 -n 1 -l 89 \\
      --ak api_base=http://${SGLANG_HOST}:${SGLANG_PORT}/v1 --ak temperature=0.5
"""

import json
from pathlib import Path

from harbor.agents.terminus_2 import Terminus2
from harbor.environments.base import BaseEnvironment
from harbor.llms.chat import Chat
from harbor.models.agent.context import AgentContext

from dhav6.harness import run_harness_loop
from dhav6.output_validator import OutputValidator
from dhav6.terminus2_adapter import Terminus2Adapter
from dhav6.token_tracker import TokenTracker
from dhav6.utils import parse_bool


class DHAv6Agent(Terminus2):
    """DHAv6 on terminus-2: agent-agnostic harness with terminus-2 adapter."""

    def __init__(self, *args, **kwargs):
        self._enable_curator = parse_bool(kwargs.pop("enable_curator", True))
        self._enable_validator = parse_bool(kwargs.pop("enable_validator", True))
        self._curator_api_base = kwargs.pop("curator_api_base", None)
        self._validator_api_base = kwargs.pop("validator_api_base", None)
        self._curator_budget = int(kwargs.pop("curator.budget", 50000))
        self._curator_reserved_turns = int(kwargs.pop("curator.reserved_turns", 15))

        self._validator_duplicate_window = int(kwargs.pop("validator.rules.duplicate_window", 5))
        self._validator_l2_enabled = parse_bool(
            kwargs.pop("validator.task_understanding.enabled", True)
        )
        self._validator_l2_mode = kwargs.pop("validator.task_understanding.mode", "tolerant")
        self._validator_l2_model = kwargs.pop("validator.task_understanding.model", None)
        self._validator_l2_max_tokens = int(
            kwargs.pop("validator.task_understanding.max_tokens", 4096)
        )

        self._harness_api_base = kwargs.get("api_base", "http://${SGLANG_HOST}:${SGLANG_PORT}/v1")
        self._harness_model = kwargs.get("model_name", "openai/glm-4.7-flash")

        super().__init__(*args, **kwargs)

        if self._enable_curator:
            self._enable_summarize = False

        self._token_tracker = TokenTracker()

        validator_api = self._validator_api_base or self._harness_api_base
        self._validator = OutputValidator(
            token_tracker=self._token_tracker,
            duplicate_window=self._validator_duplicate_window,
            task_understanding_enabled=self._validator_l2_enabled,
            task_understanding_mode=self._validator_l2_mode,
            task_understanding_api_base=validator_api,
            task_understanding_model=self._validator_l2_model or self._harness_model,
            task_understanding_max_tokens=self._validator_l2_max_tokens,
        )

        self.logger.info(
            f"[dhav6] curator={self._enable_curator} validator={self._enable_validator} "
            f"l2={self._validator_l2_enabled} harness_api={self._harness_api_base}"
        )

    @staticmethod
    def name() -> str:
        return "dhav6-terminus2"

    def version(self) -> str | None:
        return "6.0.0"

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        self._original_instruction = instruction
        try:
            await super().run(instruction, environment, context)
        finally:
            try:
                self._save_token_tracker()
            except Exception:
                pass

    async def _run_agent_loop(
        self,
        initial_prompt: str,
        chat: Chat,
        logging_dir: Path | None = None,
        original_instruction: str = "",
    ) -> None:
        if self._context is None:
            raise RuntimeError("Agent context is not set.")
        if self._session is None:
            raise RuntimeError("Session is not set.")

        self._context.n_input_tokens = 0
        self._context.n_output_tokens = 0
        self._context.n_cache_tokens = 0
        self._context.cost_usd = None

        adapter = Terminus2Adapter(self, chat, self._session)
        raw_jsonl_path = self.logs_dir / "raw.jsonl"
        curator_api = self._curator_api_base or self._harness_api_base

        n_episodes = await run_harness_loop(
            adapter=adapter,
            initial_prompt=initial_prompt,
            original_instruction=original_instruction,
            raw_jsonl_path=raw_jsonl_path,
            logging_dir=logging_dir,
            trajectory_steps=self._trajectory_steps,
            dump_trajectory=self._dump_trajectory,
            token_tracker=self._token_tracker,
            enable_curator=self._enable_curator,
            curator_api_base=curator_api,
            curator_model=self._harness_model,
            curator_budget=self._curator_budget,
            curator_reserved_turns=self._curator_reserved_turns,
            enable_validator=self._enable_validator,
            validator=self._validator,
        )

        self._n_episodes = n_episodes
        self._context.n_input_tokens = chat.total_input_tokens
        self._context.n_output_tokens = chat.total_output_tokens
        self._context.n_cache_tokens = chat.total_cache_tokens
        self._context.cost_usd = chat.total_cost if chat.total_cost > 0 else None

        self._save_token_tracker()

    def _save_token_tracker(self):
        tracker_path = self.logs_dir / "dhav6_tokens.json"
        self._token_tracker.save(tracker_path)
        self.logger.info(f"[dhav6] token stats: {json.dumps(self._token_tracker.to_dict(), indent=2)}")
