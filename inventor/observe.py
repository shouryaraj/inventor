"""Observability: traces, generations and scores, sent to Langfuse when configured.

Backend analogy: this is distributed tracing for the pipeline. A run is a trace,
each stage is a span, each model call is a generation (model, tokens, cost,
latency), and the run's health metrics are scores attached to the trace.

The default `Tracer` does nothing, so the pipeline never depends on Langfuse.
`make_tracer()` returns a `LangfuseTracer` only when both keys are set and the
`observe` extra is installed. Every number sent as a score is computed by code.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class NullSpan:
    id: str | None = None
    trace_id: str | None = None

    def update(self, **_: Any) -> None:
        pass

    def score(self, **_: Any) -> None:
        pass

    def score_trace(self, **_: Any) -> None:
        pass


class Tracer:
    """No-op tracer: the default."""

    enabled = False

    @contextmanager
    def span(self, name: str, *, as_type: str = "span", **fields: Any) -> Iterator[Any]:
        yield NullSpan()

    @contextmanager
    def trace(self, name: str, *, tags: list[str] | None = None, **fields: Any) -> Iterator[Any]:
        yield NullSpan()

    def score_observation(self, trace_id: str | None, observation_id: str | None, name: str,
                          value: float | str, comment: str | None = None) -> None:
        pass

    def trace_url(self, trace_id: str | None) -> str | None:
        return None

    def flush(self) -> None:
        pass


class LangfuseTracer(Tracer):
    enabled = True

    def __init__(self, client: Any = None) -> None:
        if client is None:
            from langfuse import Langfuse

            client = Langfuse()
        self.client = client

    @contextmanager
    def span(self, name: str, *, as_type: str = "span", **fields: Any) -> Iterator[Any]:
        with self.client.start_as_current_observation(name=name, as_type=as_type, **fields) as obs:
            yield obs

    @contextmanager
    def trace(self, name: str, *, tags: list[str] | None = None, **fields: Any) -> Iterator[Any]:
        from langfuse import propagate_attributes

        with propagate_attributes(trace_name=name, tags=tags or []), self.span(name, **fields) as root:
            yield root

    def score_observation(self, trace_id, observation_id, name, value, comment=None) -> None:
        if trace_id:
            self.client.create_score(trace_id=trace_id, observation_id=observation_id, name=name,
                                     value=value, comment=comment)

    def trace_url(self, trace_id: str | None) -> str | None:
        try:
            return self.client.get_trace_url(trace_id=trace_id) if trace_id else None
        except Exception:  # URL is a convenience; never fail a run over it
            return None

    def flush(self) -> None:
        self.client.flush()


def langfuse_configured() -> tuple[bool, str]:
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return False, "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set"
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return False, "install the extra: uv sync --extra observe"
    return True, os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "cloud default"


def make_tracer(enabled: bool = True) -> Tracer:
    ok, _ = langfuse_configured()
    return LangfuseTracer() if enabled and ok else Tracer()


def load_env_file(path: str = ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines; never overrides variables already set."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)
