"""SGLang backend for metaharness.

Routes the metaharness proposer through a single OpenAI-compatible SGLang
endpoint instead of the Codex/Gemini CLIs. Wired in via metaharness.json:

    "backend_plugins": {
      "sglang": {
        "factory": "metaharness_plugin.sglang_backend:create_backend",
        "options": {
          "base_url": "http://HOST:8051/v1",
          "model":    "qwen3.5-35b-a3b",
          "api_key":  "dummy",
          "temperature": 0.5,
          "max_tokens":  8192,
          "max_workspace_chars_per_file": 12000,
          "max_workspace_files": 40,
          "response_mode": "tool_native"
        }
      }
    }

`response_mode` selects how the proposer payload is returned:
    - "tool_native" (default) — OpenAI tool calling with tool_choice="auto".
                                The model emits its NATIVE tool-call format
                                (Qwen3-Coder XML
                                `<tool_call><function=name><parameter=...>` /
                                GLM-4.7 `<tool_call>name<arg_key>...<arg_value>...`)
                                into content; SGLang's qwen3_coder / glm47
                                detector converts that XML into OpenAI-shaped
                                tool_calls at the API boundary, so the client
                                still reads `tool_calls[0].function.arguments`.
                                No grammar constraint — relies on the chat
                                template and the model's training.
    - "tool_json"             — OpenAI tool calling with tool_choice="required".
                                SGLang installs a JSON-schema grammar
                                constraint, forcing
                                `[{"name":..., "parameters":...}]` JSON output.
                                Bypasses the model's native XML format.
                                More robust against malformed output, less
                                "native".
    - "json_fence"            — legacy: model emits a ```json ... ``` block
                                inside chat content; client parses it.

Override via the `SGLANG_RESPONSE_MODE` env var. The string `"tool"` is
accepted as a back-compat alias for `"tool_json"`.

Then invoked as `metaharness run <project> --backend sglang ...`.

Proposer protocol (see metaharness.proposer.base.ProposerBackend):
    - prepare(request) -> request
    - invoke(request)  -> ProposalExecution      (does the actual LLM call)
    - collect(execution) -> ProposalResult
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# The metaharness package is importable because run_metaharness.sh adds
# baselines/metaharness/src to PYTHONPATH.
from metaharness.models import (
    AgentEvent,
    ProposalExecution,
    ProposalRequest,
    ProposalResult,
)


_DEFAULT_BASE_URL = "http://127.0.0.1:8051/v1"
_DEFAULT_API_KEY = "dummy"
_DEFAULT_MODEL = "qwen3.5-35b-a3b"
_DEFAULT_TEMPERATURE = 0.5
_DEFAULT_MAX_TOKENS = 8192
_DEFAULT_TIMEOUT = 600.0
_DEFAULT_MAX_FILES = 40
_DEFAULT_MAX_CHARS = 12000
_DEFAULT_RESPONSE_MODE = "tool_native"
# `tool` is a back-compat alias for `tool_json` — early versions of this plugin
# exposed only `"tool"` and `"json_fence"`.
_VALID_RESPONSE_MODES = {"tool_native", "tool_json", "tool", "json_fence"}
_PROPOSE_EDITS_TOOL_NAME = "propose_edits"

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _propose_edits_tool_schema() -> dict[str, Any]:
    """JSON schema describing the proposer's tool-call arguments.

    With tool_choice="required", SGLang turns this into a grammar
    constraint, so the model's native tool-call format (Qwen3 XML,
    GLM <tool_call> tokens, etc.) is bypassed in favor of a JSON
    array of {name, parameters} pairs. The OpenAI-compatible response
    then surfaces `arguments` as a JSON string we can json.loads().
    """

    return {
        "type": "function",
        "function": {
            "name": _PROPOSE_EDITS_TOOL_NAME,
            "description": (
                "Propose a set of file edits that improve the harness for the "
                "given objective. Provide FULL file contents in `content` "
                "(not a patch)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One-line description of the change.",
                    },
                    "final_text": {
                        "type": "string",
                        "description": "Longer rationale for the change.",
                    },
                    "files": {
                        "type": "array",
                        "description": "List of file edits to apply.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "relative_path": {
                                    "type": "string",
                                    "description": "Path relative to the workspace root.",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "FULL new file contents.",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["write", "append"],
                                    "description": "write=overwrite, append=concat. Defaults to write.",
                                },
                            },
                            "required": ["relative_path", "content"],
                        },
                    },
                    "change_manifest": {
                        "type": "object",
                        "description": (
                            "Optional metaharness change manifest "
                            "(schema_version=metaharness.change_manifest.v1)."
                        ),
                    },
                },
                "required": ["summary", "files"],
            },
        },
    }


def create_backend(*, backend_name: str, project: Any, options: Mapping[str, Any]):
    """Factory hook for metaharness's backend_plugins mechanism."""

    return SglangBackend(name=backend_name, options=dict(options or {}))


class SglangBackend:
    """One-shot OpenAI-compatible proposer that talks to SGLang."""

    def __init__(self, *, name: str, options: Mapping[str, Any]):
        self.name = name
        opts = dict(options)
        self.base_url: str = str(opts.get("base_url") or os.environ.get("SGLANG_BASE_URL") or _DEFAULT_BASE_URL)
        self.api_key: str = str(opts.get("api_key") or os.environ.get("SGLANG_API_KEY") or _DEFAULT_API_KEY)
        self.model: str = str(opts.get("model") or os.environ.get("SGLANG_MODEL") or _DEFAULT_MODEL)
        self.temperature: float = float(opts.get("temperature", _DEFAULT_TEMPERATURE))
        self.max_tokens: int = int(opts.get("max_tokens", _DEFAULT_MAX_TOKENS))
        self.timeout: float = float(opts.get("timeout", _DEFAULT_TIMEOUT))
        self.max_files: int = int(opts.get("max_workspace_files", _DEFAULT_MAX_FILES))
        self.max_chars: int = int(opts.get("max_workspace_chars_per_file", _DEFAULT_MAX_CHARS))
        self.extra_chat_kwargs: dict[str, Any] = dict(opts.get("extra_chat_kwargs") or {})

        mode = str(
            opts.get("response_mode")
            or os.environ.get("SGLANG_RESPONSE_MODE")
            or _DEFAULT_RESPONSE_MODE
        ).lower()
        if mode == "tool":
            mode = "tool_json"  # back-compat alias
        if mode not in _VALID_RESPONSE_MODES:
            raise ValueError(
                f"response_mode must be one of {sorted(_VALID_RESPONSE_MODES)}, got {mode!r}"
            )
        self.response_mode: str = mode

    # ProposerBackend protocol -------------------------------------------------

    def prepare(self, request: ProposalRequest) -> ProposalRequest:
        return request

    def invoke(self, request: ProposalRequest) -> ProposalExecution:
        proposal_dir = request.candidate_dir / "proposal"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = proposal_dir / "stdout.jsonl"
        stderr_path = proposal_dir / "stderr.txt"

        from openai import OpenAI  # local import keeps the plugin lightweight to load

        client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)

        system_prompt = _render_system_prompt(self.response_mode)
        user_prompt = _render_user_prompt(
            request=request,
            max_files=self.max_files,
            max_chars=self.max_chars,
            response_mode=self.response_mode,
        )

        events: list[dict[str, Any]] = []
        response_text = ""
        tool_arguments: str | None = None
        returncode = 0
        usage: dict[str, int] = {}
        error_text = ""

        chat_kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.response_mode in {"tool_native", "tool_json"}:
            chat_kwargs["tools"] = [_propose_edits_tool_schema()]
            chat_kwargs["parallel_tool_calls"] = False
            if self.response_mode == "tool_json":
                # tool_choice="required" installs a JSON-schema grammar
                # constraint, so the model emits [{"name":..., "parameters":...}]
                # JSON. This bypasses the model's native tool-call format.
                chat_kwargs["tool_choice"] = "required"
            else:
                # tool_choice="auto" lets the model emit its native tool-call
                # format (Qwen3-Coder XML <tool_call><function=...><parameter=...>
                # / GLM-4.7 <tool_call>name<arg_key>...<arg_value>...). The
                # SGLang server's qwen3_coder / glm47 detector then converts
                # that XML into OpenAI-shaped tool_calls at the API boundary,
                # so client-side parsing is identical to tool_json mode.
                # Note: no grammar constraint, so we rely on (a) the chat
                # template injecting tool defs in the format the model was
                # trained on, and (b) a strong "call the tool" instruction.
                chat_kwargs["tool_choice"] = "auto"
        chat_kwargs.update(self.extra_chat_kwargs)

        try:
            response = client.chat.completions.create(**chat_kwargs)
            choice = response.choices[0] if response.choices else None
            message = choice.message if choice is not None else None
            response_text = (message.content or "") if message is not None else ""
            tool_calls = getattr(message, "tool_calls", None) if message is not None else None
            if tool_calls:
                first = tool_calls[0]
                fn = getattr(first, "function", None)
                tool_arguments = getattr(fn, "arguments", None) if fn is not None else None
            if response.usage is not None:
                usage = {
                    "prompt_tokens": int(getattr(response.usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(response.usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(response.usage, "total_tokens", 0) or 0),
                }
            events.append(
                {
                    "kind": "llm_response",
                    "model": self.model,
                    "base_url": self.base_url,
                    "response_mode": self.response_mode,
                    "usage": usage,
                    "text": response_text,
                    "tool_arguments": tool_arguments,
                }
            )
        except Exception as exc:  # pragma: no cover - surface real failures into stderr
            returncode = 1
            error_text = f"{type(exc).__name__}: {exc}"
            events.append({"kind": "error", "text": error_text})

        parsed = _extract_proposal(
            response_text,
            tool_arguments=tool_arguments,
            response_mode=self.response_mode,
        )
        applied_files: list[str] = []
        skipped: list[dict[str, Any]] = []
        if returncode == 0 and parsed is not None:
            applied_files, skipped = _apply_file_edits(
                request=request,
                files=parsed.get("files") or [],
            )
            manifest = parsed.get("change_manifest")
            if isinstance(manifest, Mapping):
                manifest_path = request.workspace_dir / ".metaharness" / "change_manifest.json"
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(
                    json.dumps(dict(manifest), indent=2, sort_keys=True), encoding="utf-8"
                )
            events.append(
                {
                    "kind": "file_changes",
                    "applied": applied_files,
                    "skipped": skipped,
                }
            )

        stdout_path.write_text(
            "\n".join(json.dumps(event, default=str) for event in events) + ("\n" if events else ""),
            encoding="utf-8",
        )
        stderr_path.write_text(error_text, encoding="utf-8")

        execution = ProposalExecution(
            command=["sglang", self.base_url, self.model],
            cwd=request.workspace_dir,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            returncode=returncode,
            metadata={
                "parsed_proposal": parsed,
                "applied_files": applied_files,
                "skipped_files": skipped,
                "usage": usage,
                "summary": (parsed or {}).get("summary", "") if isinstance(parsed, Mapping) else "",
                "final_text": (parsed or {}).get("final_text", "") if isinstance(parsed, Mapping) else "",
                "error": error_text,
            },
        )
        return execution

    def collect(self, execution: ProposalExecution) -> ProposalResult:
        meta = execution.metadata or {}
        applied = list(meta.get("applied_files") or [])
        usage = dict(meta.get("usage") or {})
        summary = str(meta.get("summary") or "")
        final_text = str(meta.get("final_text") or summary)
        error_text = str(meta.get("error") or "")

        applied_flag = bool(applied)
        if not applied_flag and not summary:
            summary = error_text or "No proposal was applied."

        events = [
            AgentEvent(
                ts=None,
                kind="file_change" if applied_flag else "no_change",
                text=summary,
                file_changes=applied,
            )
        ]
        return ProposalResult(
            applied=applied_flag,
            summary=summary,
            final_text=final_text,
            changed_files=applied,
            events=events,
            raw_stdout_path=execution.stdout_path,
            raw_stderr_path=execution.stderr_path,
            token_usage=usage,
            metadata={
                "command": execution.command,
                "returncode": execution.returncode,
                "skipped_files": meta.get("skipped_files", []),
                "parsed_proposal": meta.get("parsed_proposal"),
                "error": error_text,
            },
        )


# Prompt construction ---------------------------------------------------------


_COMMON_INTRO = (
    "You are an automated harness optimizer for the Meta-Harness framework.\n"
    "You will be given an objective, constraints, an allowed write-scope, a\n"
    "snapshot of the current workspace, and an evaluation contract. Propose\n"
    "concrete file edits that improve the harness for the given objective.\n"
    "\n"
    "Rules:\n"
    "- Only edit paths under the allowed write-scope. Off-scope files are dropped.\n"
    "- `content` must be the FULL new file contents, not a patch.\n"
    "- `mode` is \"write\" (overwrite) or \"append\"; defaults to \"write\".\n"
)


def _render_system_prompt(response_mode: str) -> str:
    if response_mode in {"tool_native", "tool_json"}:
        return (
            _COMMON_INTRO
            + "\n"
            + "Call the `propose_edits` tool exactly once with your proposal.\n"
            + "Use the tool-call format you were trained on; do NOT also emit\n"
            + "a JSON block in your reply.\n"
            + "Provide `summary` and `files` at minimum. You may also include\n"
            + "`final_text` (longer rationale) and `change_manifest`\n"
            + "(schema_version=\"metaharness.change_manifest.v1\", with a\n"
            + "`changes` array of {id, component, description, files,\n"
            + "failure_pattern, root_cause, targeted_fix, predicted_fixes,\n"
            + "risk_tasks, evidence_refs}).\n"
        )
    # json_fence mode
    return (
        _COMMON_INTRO
        + "\n"
        + "Reply with exactly ONE fenced ```json ... ``` block at the end of\n"
        + "your answer, using this shape:\n"
        + "\n"
        + "```json\n"
        + "{\n"
        + "  \"summary\": \"one-line description of the change\",\n"
        + "  \"final_text\": \"longer rationale\",\n"
        + "  \"files\": [\n"
        + "    {\"relative_path\": \"AGENTS.md\", \"content\": \"FULL FILE CONTENTS\", \"mode\": \"write\"}\n"
        + "  ],\n"
        + "  \"change_manifest\": {\n"
        + "    \"schema_version\": \"metaharness.change_manifest.v1\",\n"
        + "    \"changes\": [\n"
        + "      {\"id\": \"change-1\", \"component\": \"docs\", \"description\": \"...\",\n"
        + "       \"files\": [\"AGENTS.md\"], \"failure_pattern\": \"...\",\n"
        + "       \"root_cause\": \"...\", \"targeted_fix\": \"...\",\n"
        + "       \"predicted_fixes\": [], \"risk_tasks\": [], \"evidence_refs\": []}\n"
        + "    ]\n"
        + "  }\n"
        + "}\n"
        + "```\n"
        + "\n"
        + "Output exactly one JSON block; everything else is ignored when extracting.\n"
    )


def _render_user_prompt(
    *,
    request: ProposalRequest,
    max_files: int,
    max_chars: int,
    response_mode: str = "json_fence",
) -> str:
    instr = request.instructions
    backend_prompt = ""
    try:
        backend_prompt = request.prompt_path.read_text(encoding="utf-8")
    except OSError:
        backend_prompt = ""

    bootstrap_summary = ""
    try:
        if request.bootstrap_summary_path and request.bootstrap_summary_path.exists():
            bootstrap_summary = request.bootstrap_summary_path.read_text(encoding="utf-8")
    except OSError:
        bootstrap_summary = request.bootstrap_summary_text or ""

    workspace_blob = _render_workspace_snapshot(
        request.workspace_dir,
        max_files=max_files,
        max_chars=max_chars,
    )

    sections: list[str] = []
    sections.append(f"# Candidate: {request.candidate_id}")
    if request.parent_candidate_ids:
        sections.append(f"Parent candidates: {', '.join(request.parent_candidate_ids)}")

    sections.append("\n## Objective\n" + (instr.objective or ""))
    if instr.constraints:
        sections.append("\n## Constraints\n" + "\n".join(f"- {c}" for c in instr.constraints))
    if instr.workspace_layout:
        sections.append("\n## Workspace Layout\n" + instr.workspace_layout)
    if instr.allowed_actions:
        sections.append("\n## Allowed Actions\n" + "\n".join(f"- {a}" for a in instr.allowed_actions))
    if instr.forbidden_actions:
        sections.append("\n## Forbidden Actions\n" + "\n".join(f"- {a}" for a in instr.forbidden_actions))
    if instr.evaluation_contract:
        sections.append("\n## Evaluation Contract\n" + instr.evaluation_contract)
    if backend_prompt.strip():
        sections.append("\n## Proposer Instructions\n" + backend_prompt.strip())
    if bootstrap_summary.strip():
        sections.append("\n## Environment Bootstrap\n" + bootstrap_summary.strip())
    sections.append("\n## Current Workspace Snapshot\n" + workspace_blob)
    if response_mode in {"tool_native", "tool_json"}:
        sections.append(
            "\nCall the `propose_edits` tool now with your proposal."
        )
    else:
        sections.append(
            "\nProduce your single JSON block now. Do not include explanations after the JSON."
        )
    return "\n".join(sections)


def _render_workspace_snapshot(workspace_dir: Path, *, max_files: int, max_chars: int) -> str:
    files: list[Path] = []
    for path in sorted(workspace_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(workspace_dir)
        # Skip metaharness internal state and obvious binary cruft
        if rel.parts and rel.parts[0] in {".metaharness", ".git", "__pycache__", "runs", "node_modules"}:
            continue
        files.append(path)
        if len(files) >= max_files:
            break

    chunks: list[str] = []
    for path in files:
        rel = path.relative_to(workspace_dir)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            chunks.append(f"### {rel}\n[binary or unreadable; skipped]\n")
            continue
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated at {max_chars} chars] ..."
        chunks.append(f"### {rel}\n```\n{text}\n```\n")
    if not chunks:
        return "(empty workspace)"
    return "\n".join(chunks)


# Response parsing ------------------------------------------------------------


def _extract_proposal(
    text: str,
    *,
    tool_arguments: str | None = None,
    response_mode: str = "json_fence",
) -> dict[str, Any] | None:
    """Extract the proposal payload.

    In `tool` mode the SGLang server returns the proposer's arguments as
    a JSON string in `message.tool_calls[0].function.arguments`. If that
    is present we json.loads() it directly. Otherwise (or in
    `json_fence` mode) fall back to scanning the assistant content for a
    ```json ... ``` block or a bare {...} blob — this also rescues the
    occasional case where Qwen3-Coder leaks a `<tool_call>{...}</tool_call>`
    in plain content without engaging the tool pathway.
    """

    if response_mode in {"tool_native", "tool_json"} and tool_arguments:
        try:
            data = json.loads(tool_arguments)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data

    if not text:
        return None
    match = _JSON_FENCE.search(text)
    payload = match.group(1) if match else None
    if payload is None:
        # try the bare-JSON case: find last "{" .. last "}" with matching braces
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        payload = text[first : last + 1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _apply_file_edits(
    *,
    request: ProposalRequest,
    files: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    applied: list[str] = []
    skipped: list[dict[str, Any]] = []
    if not isinstance(files, list):
        return applied, skipped

    workspace = request.workspace_dir.resolve()
    for entry in files:
        if not isinstance(entry, Mapping):
            skipped.append({"reason": "not_a_mapping", "entry": str(entry)[:200]})
            continue
        rel_path = str(entry.get("relative_path") or "").strip()
        if not rel_path:
            skipped.append({"reason": "missing_relative_path", "entry": dict(entry)})
            continue
        target = (workspace / rel_path).resolve()
        try:
            target.relative_to(workspace)
        except ValueError:
            skipped.append({"reason": "outside_workspace", "relative_path": rel_path})
            continue
        content = entry.get("content")
        if not isinstance(content, str):
            skipped.append({"reason": "missing_content", "relative_path": rel_path})
            continue
        mode = str(entry.get("mode") or "write").lower()
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and target.exists():
            try:
                existing = target.read_text(encoding="utf-8")
            except OSError:
                existing = ""
            target.write_text(existing + content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")
        applied.append(rel_path)
    return applied, skipped


# Direct invocation (debugging) -----------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    print("metaharness_plugin.sglang_backend — factory is create_backend", file=sys.stderr)
    sys.exit(0)
