"""Backend: the Claude Code CLI in headless mode (`claude -p`).

Uses the caller's Claude Code login, so no API key is needed. Each call runs with
a custom system prompt, no tools, no MCP servers, no settings and no session
persistence, from an empty working directory. That keeps the request small
(about 1k input tokens of overhead instead of Claude Code's full agent prompt)
and stops the model from acting on the machine.

`total_cost_usd` is what the CLI reports. On a subscription plan it is an
API-equivalent estimate, which is still the right unit for a spend cap.
"""

from __future__ import annotations

import asyncio
import json
import tempfile

from inventor.llm.base import LLMError, LLMRequest, LLMResult


class ClaudeCLIBackend:
    name = "claude-cli"

    def __init__(self, executable: str = "claude", timeout_s: float = 300.0) -> None:
        self.executable = executable
        self.timeout_s = timeout_s
        self._workdir = tempfile.mkdtemp(prefix="inventor-llm-")

    def _args(self, request: LLMRequest) -> list[str]:
        args = [
            self.executable, "-p",
            "--output-format", "json",
            "--model", request.model,
            "--system-prompt", request.system,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
        ]
        if request.schema is not None:
            args += ["--json-schema", json.dumps(request.schema)]
        return args

    async def complete(self, request: LLMRequest) -> LLMResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._args(request),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
            )
        except FileNotFoundError as exc:
            raise LLMError(
                f"'{self.executable}' not found; install Claude Code or use --backend anthropic-api"
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(request.prompt.encode()), self.timeout_s)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise LLMError(f"claude CLI timed out after {self.timeout_s:.0f} s") from exc

        try:
            out = json.loads(stdout)
        except json.JSONDecodeError as exc:
            detail = (stderr or stdout).decode(errors="replace")[:500]
            raise LLMError(f"claude CLI returned non-JSON output (exit {proc.returncode}): {detail}") from exc
        if out.get("is_error") or out.get("subtype") != "success":
            raise LLMError(f"claude CLI error: {str(out.get('result'))[:500]}")

        text = out.get("result") or ""
        data = None
        if request.schema is not None:
            data = out.get("structured_output")
            if data is None:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LLMError("structured output requested but none returned") from exc
        usage = out.get("usage") or {}
        return LLMResult(
            text=text,
            data=data,
            cost_usd=float(out.get("total_cost_usd") or 0.0),
            input_tokens=int(usage.get("input_tokens", 0))
            + int(usage.get("cache_creation_input_tokens", 0))
            + int(usage.get("cache_read_input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
