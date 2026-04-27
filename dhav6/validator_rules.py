"""Layer 1: pure Python rule checks for the output validator.

No LLM calls. No I/O beyond what's passed in. Returns a RuleReject
dataclass on failure, None on pass.
"""

import re
import shlex
from dataclasses import dataclass


@dataclass
class CommandRecord:
    """One executed command and its outcome, maintained by the validator."""
    keystrokes: str
    observation: str
    turn: int
    has_error: bool


@dataclass
class RuleReject:
    """Structured rejection from a rule check."""
    rule: str
    reason: str
    suggestion: str = ""
    evidence_turn: int | None = None
    first_error_line: str | None = None
    no_state_change_detail: str | None = None


ERROR_INDICATORS = [
    "Error", "error:", "ERROR",
    "Traceback", "No such file", "command not found",
    "Permission denied", "not found", "cannot ",
    "fatal:", "FAILED", "panic:", "Errno", "Exception",
]

STATE_CHANGE_INDICATORS = [
    "cat >", "cat >>", "tee ", "sed -i", "echo >", "echo >>",
    "> /", ">> /", "patch ", "git apply", "git checkout",
    "git reset", "git pull", "pip install", "npm install",
    "apt install", "uv pip", "cd ", "pushd", "popd",
    "export ", "source ", "make", "cmake", "cargo build",
    "chmod ", "chown ", "mv ", "cp ", "rm ",
    "python3 -c", "python -c", "node -e",
    "<<",
]

SIMPLE_COMMANDS = {
    "ls", "dir", "cat", "head", "tail", "less", "more", "nl",
    "grep", "egrep", "fgrep", "rg", "ag", "ack",
    "find", "locate", "tree", "du", "df",
    "wc", "file", "which", "type", "whereis", "readlink",
    "pwd", "whoami", "id", "env", "printenv",
    "echo", "printf",
    "diff", "cmp", "comm",
    "man", "help", "info",
    "date", "uptime", "uname", "hostname",
    "ps", "top", "htop", "free", "vmstat", "iostat",
    "cd", "pushd", "popd",
    "true", "false", "test",
}

SIMPLE_GIT_SUBCOMMANDS = {
    "log", "status", "diff", "show", "branch", "remote",
    "tag", "stash", "blame", "shortlog", "reflog",
}

SUBMISSION_SENTINEL = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def observation_has_error(obs: str) -> bool:
    if not obs or not obs.strip():
        return True
    for indicator in ERROR_INDICATORS:
        if indicator in obs:
            return True
    return False


def _first_error_line(obs: str) -> str | None:
    if not obs:
        return None
    for line in obs.split("\n"):
        line_s = line.strip()
        if not line_s:
            continue
        for indicator in ERROR_INDICATORS:
            if indicator in line_s:
                return line_s[:200]
    return None


def _has_state_change(records: list[CommandRecord]) -> bool:
    for rec in records:
        ks = rec.keystrokes
        for prefix in STATE_CHANGE_INDICATORS:
            if prefix in ks:
                return True
    return False


def check_empty(keystrokes_list: list[str]) -> RuleReject | None:
    non_empty = [ks for ks in keystrokes_list if ks.strip()]
    if not non_empty:
        return RuleReject(
            rule="empty",
            reason="Empty or whitespace-only command. Provide an actual command.",
            suggestion=(
                "If waiting for a background process, check its status explicitly "
                "(e.g., `ps aux | grep <process>`, `jobs`, or `cat <logfile>`). "
                "If waiting for output, use `sleep N && <check command>`."
            ),
        )
    return None


def check_duplicate(
    proposed_keystrokes: list[str],
    history: list[CommandRecord],
    window: int,
) -> RuleReject | None:
    """Check if any proposed command is an exact duplicate of a recent failed command
    with no intervening state change."""
    start = max(0, len(history) - window)
    for proposed_ks in proposed_keystrokes:
        proposed_stripped = proposed_ks.strip()
        if not proposed_stripped:
            continue
        for i in range(start, len(history)):
            rec = history[i]
            if rec.keystrokes.strip() != proposed_stripped:
                continue
            if not rec.has_error and rec.observation.strip():
                continue
            if _has_state_change(history[i + 1:]):
                continue
            return RuleReject(
                rule="duplicate",
                reason=(
                    f"Exact duplicate of command at turn {rec.turn} which "
                    f"{'produced an error' if rec.has_error else 'produced no output'}. "
                    f"No intervening change that would affect the result."
                ),
                suggestion=(
                    "Fix the underlying issue before retrying: edit the relevant file, "
                    "install a missing dependency, change directory, or try a fundamentally "
                    "different command."
                ),
                evidence_turn=rec.turn,
                first_error_line=_first_error_line(rec.observation),
                no_state_change_detail=(
                    f"No file edits, installs, or directory changes since turn {rec.turn}."
                ),
            )
    return None


def check_cyclic(
    proposed_keystrokes: list[str],
    history: list[CommandRecord],
    window: int,
) -> RuleReject | None:
    """Detect A-B-A-B or A-B-C-A-B-C cyclic repetition patterns."""
    recent_keys = [h.keystrokes.strip() for h in history[-window:]]
    sequence = recent_keys + [ks.strip() for ks in proposed_keystrokes if ks.strip()]

    for period in range(2, 4):
        if len(sequence) < 2 * period:
            continue
        tail = sequence[-(2 * period):]
        first_half = tail[:period]
        second_half = tail[period:]
        if first_half == second_half:
            cycle_desc = " → ".join(f"`{k[:60]}`" for k in first_half)
            return RuleReject(
                rule="cyclic",
                reason=(
                    f"Cyclic repetition detected (period {period}): "
                    f"the pattern [{cycle_desc}] has repeated."
                ),
                suggestion=(
                    "You are repeating the same sequence of commands. "
                    "Step back and reconsider your approach: read the error messages "
                    "from earlier attempts, identify what specifically is failing, "
                    "and try a different strategy."
                ),
                evidence_turn=history[-1].turn if history else None,
            )
    return None


def check_syntax(keystrokes_list: list[str]) -> RuleReject | None:
    """Check for unclosed quotes or unterminated escapes via shlex."""
    for ks in keystrokes_list:
        stripped = ks.strip()
        if not stripped or len(stripped) < 3:
            continue
        try:
            shlex.split(stripped)
        except ValueError as e:
            return RuleReject(
                rule="syntax",
                reason=f"Shell syntax error: {e}. Fix the quoting before running.",
                suggestion=(
                    "Check for unclosed quotes, unmatched parentheses, or unterminated "
                    "heredocs. For multi-line scripts, use `cat > file.py << 'EOF'` with "
                    "a matching `EOF` on its own line."
                ),
                first_error_line=stripped[:200],
            )
    return None


def _get_base_command(cmd: str) -> str:
    """Extract the base command name from a command string."""
    stripped = cmd.strip()
    if not stripped:
        return ""
    first_word = stripped.split()[0]
    return first_word.rsplit("/", 1)[-1]


def _has_write_indicator(cmd: str) -> bool:
    """Check if a command contains file-write indicators."""
    if re.search(r"\s>{1,2}\s*\S", cmd):
        return True
    if re.search(r"\s>{1,2}\s*$", cmd):
        return True
    if "<<" in cmd:
        return True
    write_indicators = [
        "sed -i", "patch ", "git apply", "git am ",
        "tee ", "dd ", "install -",
    ]
    for indicator in write_indicators:
        if indicator in cmd:
            return True
    return False


def is_edit_or_submission(keystrokes: str) -> bool:
    """Determine if a command should trigger Layer 2 validation.

    Conservative: unknown commands trigger Layer 2 (prefer false positives
    over missing edits). Only whitelisted simple/exploration commands skip.
    """
    stripped = keystrokes.strip()
    if not stripped:
        return False

    if SUBMISSION_SENTINEL in stripped:
        return True

    if _has_write_indicator(stripped):
        return True

    base = _get_base_command(stripped)

    if base in SIMPLE_COMMANDS:
        return False

    if base == "git":
        parts = stripped.split()
        if len(parts) > 1 and parts[1] in SIMPLE_GIT_SUBCOMMANDS:
            return False

    return True


def format_rule_rejection(reject: RuleReject) -> str:
    """Build a human-readable rejection message from a RuleReject."""
    parts = [reject.reason]
    if reject.evidence_turn is not None:
        parts.append(f"Evidence: turn {reject.evidence_turn}.")
    if reject.first_error_line:
        parts.append(f"Error output: {reject.first_error_line}")
    if reject.no_state_change_detail:
        parts.append(reject.no_state_change_detail)
    if reject.suggestion:
        parts.append(f"Suggestion: {reject.suggestion}")
    return "\n".join(parts)
