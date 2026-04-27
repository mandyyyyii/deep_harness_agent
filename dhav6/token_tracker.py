"""Separate token accounting for harness vs generator calls.

Tracks harness LLM token usage AND fallback / action statistics so we can debug
the curator/validator without rerunning experiments.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TokenBucket:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def record(self, prompt: int, completion: int):
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total,
            "calls": self.calls,
        }


@dataclass
class PerStepRecord:
    step: int
    role: str  # "generator", "curator", "validator"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    timestamp: float = 0.0


@dataclass
class TokenTracker:
    generator: TokenBucket = field(default_factory=TokenBucket)
    curator: TokenBucket = field(default_factory=TokenBucket)
    validator: TokenBucket = field(default_factory=TokenBucket)
    per_step: list[PerStepRecord] = field(default_factory=list)

    # Curator stats
    n_curator_pass: int = 0
    n_curator_summarize: int = 0
    n_curator_fallbacks: int = 0  # parse error or api failure -> fall back to passthrough

    # Validator stats
    n_validator_rejects: int = 0       # total rejects (rule + L2)
    n_validator_passes: int = 0        # total passes (rule pass + L2 pass + L2 skip)
    n_validator_rule_rejects: int = 0  # Layer 1 rule rejections
    n_validator_l2_rejects: int = 0    # Layer 2 LLM rejections
    n_validator_l2_passes: int = 0     # Layer 2 LLM passes
    n_validator_l2_skipped: int = 0    # commands that passed rules but weren't edits (L2 not invoked)
    n_validator_l2_fallbacks: int = 0  # Layer 2 LLM parse/API failures (default to PASS)
    n_validator_skipped: int = 0       # kept for backward compat
    n_validator_fallbacks: int = 0     # kept for backward compat

    @property
    def harness_total(self) -> int:
        return self.curator.total + self.validator.total

    @property
    def generator_total(self) -> int:
        return self.generator.total

    @property
    def curator_fallback_rate(self) -> float:
        total = self.curator.calls + self.n_curator_fallbacks
        return self.n_curator_fallbacks / total if total > 0 else 0.0

    @property
    def validator_fallback_rate(self) -> float:
        total = self.validator.calls + self.n_validator_fallbacks
        return self.n_validator_fallbacks / total if total > 0 else 0.0

    @property
    def validator_reject_rate(self) -> float:
        total = self.n_validator_rejects + self.n_validator_passes
        return self.n_validator_rejects / total if total > 0 else 0.0

    def record(self, role: str, prompt_tokens: int, completion_tokens: int, step: int = 0):
        bucket = getattr(self, role)
        bucket.record(prompt_tokens, completion_tokens)
        self.per_step.append(
            PerStepRecord(
                step=step,
                role=role,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                timestamp=time.time(),
            )
        )

    def to_dict(self) -> dict:
        return {
            "generator": self.generator.to_dict(),
            "curator": self.curator.to_dict(),
            "validator": self.validator.to_dict(),
            "harness_total_tokens": self.harness_total,
            "generator_total_tokens": self.generator_total,
            "overhead_ratio": (
                self.harness_total / self.generator_total
                if self.generator_total > 0
                else 0
            ),
            "curator_stats": {
                "pass": self.n_curator_pass,
                "summarize": self.n_curator_summarize,
                "fallbacks": self.n_curator_fallbacks,
                "fallback_rate": self.curator_fallback_rate,
            },
            "validator_stats": {
                "rejects": self.n_validator_rejects,
                "passes": self.n_validator_passes,
                "rule_rejects": self.n_validator_rule_rejects,
                "l2_rejects": self.n_validator_l2_rejects,
                "l2_passes": self.n_validator_l2_passes,
                "l2_skipped": self.n_validator_l2_skipped,
                "l2_fallbacks": self.n_validator_l2_fallbacks,
                "reject_rate": self.validator_reject_rate,
            },
        }

    def save(self, path: Path):
        path.write_text(json.dumps(self.to_dict(), indent=2))
