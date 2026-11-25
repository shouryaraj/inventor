"""Shared offline fixtures: no test touches the network or a real model."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import httpx
import pytest

from inventor.llm import LLMRequest, LLMResult

FAKE_CLAUDE = """#!{python}
import json, os, sys
calls = os.environ["FAKE_CLAUDE_CALLS"]
with open(calls, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
prompt = sys.stdin.read()
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "error":
    print(json.dumps({{"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"}}))
elif mode == "garbage":
    print("not json")
else:
    print(json.dumps({{
        "type": "result", "subtype": "success", "is_error": False,
        "result": json.dumps({{"echo": prompt}}),
        "structured_output": {{"echo": prompt}},
        "total_cost_usd": 0.01,
        "usage": {{"input_tokens": 10, "cache_creation_input_tokens": 5, "output_tokens": 3}},
    }}))
"""


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch) -> tuple[str, Path]:
    exe = tmp_path / "claude"
    exe.write_text(FAKE_CLAUDE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(calls))
    return str(exe), calls


class FakeBackend:
    """Answers with whatever `respond(request)` returns as structured data."""

    name = "fake"

    def __init__(self, respond, cost: float = 0.001) -> None:
        self.respond = respond
        self.cost = cost
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        data = self.respond(request)
        return LLMResult(text=json.dumps(data), data=data, cost_usd=self.cost)


def json_transport(routes: dict[str, object]) -> httpx.MockTransport:
    """Serve canned JSON by host; record nothing else. Unknown hosts get 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.host)
        if callable(body):
            body = body(request)
        if body is None:
            return httpx.Response(404, json={"error": "not mocked"})
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)
