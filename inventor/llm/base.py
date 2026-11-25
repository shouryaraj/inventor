"""LLM contract shared by every backend, plus the budget guard and response cache.

The pipeline only talks to `LLMClient`. A backend just turns one request into one
result; the client adds caching (re-runs and tests are free), a spend cap and a
concurrency limit, identically for every backend.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from inventor.observe import Tracer


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


class BudgetExceeded(RuntimeError):
    """The run hit its spend or call cap. Raised before a call is made, never mid-call."""


@dataclass(frozen=True)
class LLMRequest:
    system: str
    prompt: str
    model: str
    schema: dict[str, Any] | None = None  # JSON Schema for structured output
    max_tokens: int = 16000


@dataclass
class LLMResult:
    text: str
    data: Any = None             # parsed structured output when a schema was given
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    trace_id: str | None = None        # where this call was traced, if tracing is on
    observation_id: str | None = None


class Backend(Protocol):
    name: str

    async def complete(self, request: LLMRequest) -> LLMResult: ...


@dataclass
class Budget:
    max_usd: float
    max_calls: int
    spent_usd: float = 0.0
    calls: int = 0

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"call cap reached ({self.calls}/{self.max_calls})")
        if self.spent_usd >= self.max_usd:
            raise BudgetExceeded(f"spend cap reached (${self.spent_usd:.4f}/${self.max_usd:.2f})")

    def record(self, result: LLMResult) -> None:
        self.calls += 1
        self.spent_usd += result.cost_usd


@dataclass
class LLMClient:
    """Cache -> budget check -> concurrency limit -> backend.

    The budget is checked inside the semaphore, so overshoot is bounded by the
    calls already in flight (at most `concurrency` x one call's cost).
    """

    backend: Backend
    budget: Budget
    cache_dir: Path | None = None
    concurrency: int = 4
    tracer: Tracer = field(default_factory=Tracer)
    cache_hits: int = 0
    _sem: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(self.concurrency)
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, request: LLMRequest) -> str:
        payload = json.dumps({"backend": self.backend.name, **asdict(request)}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    async def complete(self, request: LLMRequest, name: str = "llm") -> LLMResult:
        path = self.cache_dir / f"{self._key(request)}.json" if self.cache_dir else None
        cached = path is not None and path.exists()
        with self.tracer.span(name, as_type="generation", model=request.model,
                              input={"system": request.system, "prompt": request.prompt},
                              metadata={"backend": self.backend.name, "cached": cached}) as gen:
            if cached:
                self.cache_hits += 1
                stored = {k: v for k, v in json.loads(path.read_text()).items()
                          if k not in ("trace_id", "observation_id")}
                result = LLMResult(**{**stored, "cost_usd": 0.0, "cached": True})
            else:
                async with self._sem:
                    self.budget.check()
                    try:
                        result = await self.backend.complete(request)
                    except LLMError as exc:
                        gen.update(level="ERROR", status_message=str(exc)[:500])
                        raise
                    self.budget.record(result)
                if path is not None:
                    path.write_text(json.dumps(asdict(result)))
            gen.update(output=result.data if result.data is not None else result.text,
                       usage_details={"input": result.input_tokens, "output": result.output_tokens},
                       cost_details={"total": result.cost_usd})
            result.trace_id, result.observation_id = gen.trace_id, gen.id
        return result
