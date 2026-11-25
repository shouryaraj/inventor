"""LLM backends. Model names are per backend, chosen by role (fast / smart)."""

from __future__ import annotations

from inventor.llm.base import Backend, Budget, BudgetExceeded, LLMClient, LLMError, LLMRequest, LLMResult

BACKENDS = ("claude-cli", "anthropic-api")

# Role -> model name for each backend. The CLI accepts aliases; the API needs full ids.
MODELS: dict[str, dict[str, str]] = {
    "claude-cli": {"fast": "haiku", "smart": "sonnet"},
    "anthropic-api": {"fast": "claude-haiku-5-5", "smart": "claude-sonnet-5-5"},
}


def make_backend(name: str) -> Backend:
    if name == "claude-cli":
        from inventor.llm.claude_cli import ClaudeCLIBackend

        return ClaudeCLIBackend()
    if name == "anthropic-api":
        from inventor.llm.anthropic_api import AnthropicAPIBackend

        return AnthropicAPIBackend()
    raise ValueError(f"unknown backend {name!r}; choose from {BACKENDS}")


__all__ = [
    "BACKENDS", "MODELS", "Backend", "Budget", "BudgetExceeded", "LLMClient", "LLMError",
    "LLMRequest", "LLMResult", "make_backend",
]
