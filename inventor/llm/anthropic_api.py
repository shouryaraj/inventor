"""Backend: the Anthropic API through the official SDK (`pip install inventor[api]`).

Structured output uses `output_config.format` with a JSON schema. Cost is computed
from token usage with the price table below. Prices change; check
https://platform.claude.com/docs/en/about-claude/pricing and override
`prices_per_mtok` if they differ. An unknown model is charged at the highest
listed price, so the budget errs on the safe side.
"""

from __future__ import annotations

import json
from typing import Any

from inventor.llm.base import LLMError, LLMRequest, LLMResult

# USD per million tokens (input, output). Published list prices as of 2026-10.
DEFAULT_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class AnthropicAPIBackend:
    name = "anthropic-api"

    def __init__(self, client: Any = None, prices_per_mtok: dict[str, tuple[float, float]] | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            if client is None:
                raise LLMError("the anthropic-api backend needs: pip install 'inventor[api]'") from exc
            self._api_errors: tuple[type[BaseException], ...] = ()
        else:
            self._api_errors = (anthropic.APIError,)
            if client is None:
                client = anthropic.AsyncAnthropic()  # credentials from ANTHROPIC_API_KEY or an `ant auth login` profile
        self.client = client
        self.prices = prices_per_mtok or DEFAULT_PRICES_PER_MTOK

    def _cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        price_in, price_out = self.prices.get(model, max(self.prices.values()))
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    async def complete(self, request: LLMRequest) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": request.schema}}
        try:
            response = await self.client.messages.create(**kwargs)
        except self._api_errors as exc:
            raise LLMError(f"Anthropic API error: {type(exc).__name__}: {str(exc)[:300]}") from exc
        usage = response.usage
        input_tokens = (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        output_tokens = usage.output_tokens or 0
        cost = self._cost(request.model, input_tokens, output_tokens)  # billed even if the answer is unusable
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request", cost_usd=cost)
        if response.stop_reason == "max_tokens":
            raise LLMError("response truncated at max_tokens", cost_usd=cost)

        text = next((b.text for b in response.content if b.type == "text"), "")
        data = None
        if request.schema is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMError("structured output was not valid JSON", cost_usd=cost) from exc
        return LLMResult(text=text, data=data, cost_usd=cost, input_tokens=input_tokens, output_tokens=output_tokens)
