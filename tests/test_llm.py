import asyncio
import json

import pytest

from inventor.llm import Budget, BudgetExceeded, LLMClient, LLMError, LLMRequest
from inventor.llm.anthropic_api import AnthropicAPIBackend
from inventor.llm.claude_cli import ClaudeCLIBackend

REQ = LLMRequest(system="sys", prompt="hello", model="haiku", schema={"type": "object"})


def test_claude_cli_parses_structured_output_and_cost(fake_claude):
    exe, calls = fake_claude
    r = asyncio.run(ClaudeCLIBackend(exe).complete(REQ))
    assert r.data == {"echo": "hello"} and r.cost_usd == 0.01
    assert r.input_tokens == 15 and r.output_tokens == 3
    args = json.loads(calls.read_text().splitlines()[0])
    # Isolated call: custom system prompt, no tools, no settings, no MCP, schema passed through.
    for flag in ("--system-prompt", "--tools", "--strict-mcp-config", "--setting-sources",
                 "--no-session-persistence", "--json-schema"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""


@pytest.mark.parametrize("mode", ["error", "garbage"])
def test_claude_cli_errors_raise(fake_claude, monkeypatch, mode):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(LLMError):
        asyncio.run(ClaudeCLIBackend(fake_claude[0]).complete(REQ))


def test_cache_makes_repeat_calls_free(fake_claude, tmp_path):
    exe, calls = fake_claude
    client = LLMClient(ClaudeCLIBackend(exe), Budget(1.0, 10), cache_dir=tmp_path / "cache")
    first = asyncio.run(client.complete(REQ))
    second = asyncio.run(client.complete(REQ))
    assert not first.cached and second.cached and second.cost_usd == 0
    assert len(calls.read_text().splitlines()) == 1
    assert client.budget.calls == 1 and client.cache_hits == 1


def test_budget_caps_calls_and_spend(fake_claude):
    exe, _ = fake_claude
    by_calls = LLMClient(ClaudeCLIBackend(exe), Budget(max_usd=10, max_calls=2))
    asyncio.run(by_calls.complete(REQ))
    asyncio.run(by_calls.complete(REQ))
    with pytest.raises(BudgetExceeded):
        asyncio.run(by_calls.complete(REQ))
    by_spend = LLMClient(ClaudeCLIBackend(exe), Budget(max_usd=0.015, max_calls=100))
    asyncio.run(by_spend.complete(REQ))
    asyncio.run(by_spend.complete(REQ))  # 0.01 spent < 0.015, allowed; now 0.02
    with pytest.raises(BudgetExceeded):
        asyncio.run(by_spend.complete(REQ))


class _Messages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _response(text, stop="end_turn"):
    from types import SimpleNamespace as NS
    return NS(stop_reason=stop, content=[NS(type="text", text=text)],
              usage=NS(input_tokens=1_000_000, output_tokens=100_000,
                       cache_creation_input_tokens=0, cache_read_input_tokens=0))


def test_anthropic_backend_uses_output_config_and_prices_usage():
    from types import SimpleNamespace as NS
    messages = _Messages(_response('{"ok": true}'))
    backend = AnthropicAPIBackend(client=NS(messages=messages))
    r = asyncio.run(backend.complete(LLMRequest(system="s", prompt="p", model="claude-haiku-5-5",
                                                schema={"type": "object"})))
    assert messages.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert r.data == {"ok": True}
    assert r.cost_usd == pytest.approx(0.10 + 0.05)  # 1M in x $0.10 + 0.1M out x $0.50
    # Unknown model is charged at the highest listed price (budget errs safe).
    r2 = asyncio.run(backend.complete(LLMRequest(system="s", prompt="p", model="mystery", schema={})))
    assert r2.cost_usd == pytest.approx(4.0 + 2.0)


def test_anthropic_backend_refusal_raises():
    from types import SimpleNamespace as NS
    backend = AnthropicAPIBackend(client=NS(messages=_Messages(_response("", stop="refusal"))))
    with pytest.raises(LLMError):
        asyncio.run(backend.complete(LLMRequest(system="s", prompt="p", model="claude-haiku-5-5")))


class _Usage:
    input_tokens, output_tokens = 1000, 2000


class _ScriptedResponse:
    def __init__(self, stop_reason, text='{"ok": 1}'):
        self.stop_reason, self.usage = stop_reason, _Usage()
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class _ScriptedMessages:
    def __init__(self, outcome):
        self.outcome = outcome

    async def create(self, **_):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _api(outcome):
    return AnthropicAPIBackend(client=type("C", (), {"messages": _ScriptedMessages(outcome)})(),
                               prices_per_mtok={"haiku": (1.0, 1.0)})


def test_billed_failures_count_against_the_budget():
    client = LLMClient(_api(_ScriptedResponse("max_tokens")), Budget(1.0, 10))
    with pytest.raises(LLMError, match="truncated"):
        asyncio.run(client.complete(REQ))
    assert client.budget.calls == 1 and client.budget.spent_usd == pytest.approx(0.003)


def test_sdk_errors_become_llm_errors():
    class APIConnectionError(Exception):  # stands in for anthropic.APIError, which CI does not install
        pass

    backend = _api(APIConnectionError("connection reset"))
    backend._api_errors = (APIConnectionError,)
    with pytest.raises(LLMError, match="APIConnectionError: connection reset"):
        asyncio.run(backend.complete(REQ))


def test_non_object_structured_output_is_an_error():
    from conftest import FakeBackend

    client = LLMClient(FakeBackend(lambda r: ["not", "an", "object"]), Budget(1.0, 10))
    with pytest.raises(LLMError, match="not a JSON object"):
        asyncio.run(client.complete(REQ))
    assert client.budget.calls == 1


def test_corrupt_cache_entry_is_a_miss(fake_claude, tmp_path):
    exe, calls = fake_claude
    client = LLMClient(ClaudeCLIBackend(exe), Budget(1.0, 10), cache_dir=tmp_path / "cache")
    (tmp_path / "cache" / f"{client._key(REQ)}.json").write_text('{"text": "half wri')
    assert not asyncio.run(client.complete(REQ)).cached
    assert asyncio.run(client.complete(REQ)).cached
    assert not list((tmp_path / "cache").glob("*.tmp"))
