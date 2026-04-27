"""Append-only JSONL log of raw (action, observation) pairs per trajectory.

Written by the harness after each agent turn. Read by the curator (and later
the validator) as the single source of truth for conversation history.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RawTurn:
    turn: int
    timestamp: str
    action: str
    observation: str
    metadata: dict = field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def append_turn(path: Path, turn: RawTurn) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(turn.to_json_line() + "\n")


def read_turns(path: Path) -> list[RawTurn]:
    if not path.exists():
        return []
    turns: list[RawTurn] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            turns.append(RawTurn(
                turn=d["turn"],
                timestamp=d["timestamp"],
                action=d["action"],
                observation=d["observation"],
                metadata=d.get("metadata", {}),
            ))
    return turns


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
