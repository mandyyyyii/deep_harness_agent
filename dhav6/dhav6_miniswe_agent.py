"""
DHAv6 Mini-SWE Agent — Agent-agnostic harness with mini-swe-agent adapter.

Uses OpenAI tool-calling format with a single bash tool. Executes
commands via environment.exec(). Does not require tmux or terminus-2.

Usage:
    PYTHONPATH=dhav6 harbor run \\
      --agent-import-path dhav6_miniswe_agent:DHAv6MiniSweAgent \\
      -m openai/qwen3.5-35b-a3b -d swe-bench \\
      -o results/dhav6_swe_01 -n 1 \\
      --ak api_base=http://131.179.168.120:8054/v1
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Observation,
    ObservationResult,
    Step,
    Trajectory,
)

from dhav6.harness import run_harness_loop
from dhav6.miniswe_adapter import MiniSweAdapter
from dhav6.output_validator import OutputValidator
from dhav6.token_tracker import TokenTracker
from dhav6.utils import parse_bool

logger = logging.getLogger(__name__)

WORKFLOW_GUIDE = """## Recommended Workflow
1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works
5. Test edge cases
6. Submit: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT

## Command Execution Rules
- Each command runs in a new subshell
- Directory and environment changes are NOT persistent between commands
- Use absolute paths or chain commands with && when needed
- Response MUST include at least one bash tool call
- Submit via: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"""


class DHAv6MiniSweAgent(BaseAgent):
    """DHAv6 with mini-swe-agent style: tool-calling + env.exec()."""

    SUPPORTS_ATIF = True

    def __init__(self, *args, **kwargs):
        self._enable_curator = parse_bool(kwargs.pop("enable_curator", True))
        self._enable_validator = parse_bool(kwargs.pop("enable_validator", True))
        self._curator_api_base = kwargs.pop("curator_api_base", None)
        self._validator_api_base = kwargs.pop("validator_api_base", None)
        self._curator_budget = int(kwargs.pop("curator.budget", 50000))

        self._validator_duplicate_window = int(kwargs.pop("validator.rules.duplicate_window", 5))
        self._validator_l2_enabled = parse_bool(
            kwargs.pop("validator.task_understanding.enabled", True)
        )
        self._validator_l2_mode = kwargs.pop("validator.task_understanding.mode", "tolerant")
        self._validator_l2_model = kwargs.pop("validator.task_understanding.model", None)
        self._validator_l2_max_tokens = int(
            kwargs.pop("validator.task_understanding.max_tokens", 4096)
        )

        self._harness_api_base = kwargs.pop("api_base", "http://131.179.168.120:8054/v1")
        self._harness_model = kwargs.get("model_name", "openai/qwen3.5-35b-a3b")
        self._max_episodes = int(kwargs.pop("max_episodes", 300))
        self._temperature = float(kwargs.pop("temperature", 0.6))
        self._top_p = float(kwargs.pop("top_p", 0.95))

        super().__init__(*args, **kwargs)

        self._token_tracker = TokenTracker()
        self._trajectory_steps: list[Step] = []
        self._context: AgentContext | None = None
        self._environment: BaseEnvironment | None = None

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

        logger.info(
            f"[dhav6-miniswe] curator={self._enable_curator} validator={self._enable_validator} "
            f"l2={self._validator_l2_enabled} api={self._harness_api_base}"
        )

    @staticmethod
    def name() -> str:
        return "dhav6-miniswe"

    def version(self) -> str | None:
        return "6.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        self._environment = environment

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._context = context
        self._environment = environment
        self._context.n_input_tokens = 0
        self._context.n_output_tokens = 0
        self._context.n_cache_tokens = 0
        self._context.cost_usd = None

        initial_prompt = (
            f"Please solve this issue:\n\n{instruction}\n\n{WORKFLOW_GUIDE}"
        )

        adapter = MiniSweAdapter(
            environment=environment,
            api_base=self._harness_api_base,
            model=self._harness_model,
            max_episodes=self._max_episodes,
            temperature=self._temperature,
            top_p=self._top_p,
        )

        raw_jsonl_path = self.logs_dir / "raw.jsonl"
        curator_api = self._curator_api_base or self._harness_api_base

        try:
            n_episodes = await run_harness_loop(
                adapter=adapter,
                initial_prompt=initial_prompt,
                original_instruction=instruction,
                raw_jsonl_path=raw_jsonl_path,
                logging_dir=self.logs_dir,
                trajectory_steps=self._trajectory_steps,
                dump_trajectory=self._dump_trajectory,
                token_tracker=self._token_tracker,
                enable_curator=self._enable_curator,
                curator_api_base=curator_api,
                curator_model=self._harness_model,
                curator_budget=self._curator_budget,
                enable_validator=self._enable_validator,
                validator=self._validator,
            )
        finally:
            self._context.n_input_tokens = adapter.chat.total_input_tokens
            self._context.n_output_tokens = adapter.chat.total_output_tokens
            self._context.n_cache_tokens = adapter.chat.total_cache_tokens
            self._context.cost_usd = (
                adapter.chat.total_cost if adapter.chat.total_cost > 0 else None
            )
            self._save_token_tracker()

    def _dump_trajectory(self) -> None:
        try:
            final_metrics = None
            if self._context:
                final_metrics = FinalMetrics(
                    total_prompt_tokens=self._context.n_input_tokens or None,
                    total_completion_tokens=self._context.n_output_tokens or None,
                    total_cached_tokens=self._context.n_cache_tokens or None,
                    total_cost_usd=self._context.cost_usd,
                )

            agent_info = Agent(
                name=self.name(),
                version=self.version(),
                model_name=self.model_name or self._harness_model,
            )

            import uuid
            trajectory = Trajectory(
                session_id=str(uuid.uuid4()),
                agent=agent_info,
                steps=self._trajectory_steps,
                final_metrics=final_metrics,
            )

            path = self.logs_dir / "trajectory.json"
            path.write_text(trajectory.model_dump_json(indent=2))
        except Exception as e:
            logger.error(f"[dhav6-miniswe] trajectory dump failed: {e}")

    def _save_token_tracker(self) -> None:
        try:
            path = self.logs_dir / "dhav6_tokens.json"
            self._token_tracker.save(path)
            logger.info(
                f"[dhav6-miniswe] tokens: "
                f"{json.dumps(self._token_tracker.to_dict(), indent=2)}"
            )
        except Exception:
            pass
