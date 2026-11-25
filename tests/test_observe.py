"""Tracing with the real Langfuse SDK, exported to memory instead of a server."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from conftest import FakeBackend, json_transport
from test_pipeline import HN, respond

from inventor.llm import Budget, LLMClient
from inventor.observe import LangfuseTracer, Tracer, load_env_file
from inventor.pipeline import RunConfig, Seed, run

langfuse = pytest.importorskip("langfuse")
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402


@pytest.fixture
def traced(tmp_path):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()  # private provider; Langfuse adds its processor around `exporter`
    # Langfuse keeps one client per public key, so each test gets its own key.
    client = langfuse.Langfuse(public_key=f"pk-lf-{uuid.uuid4().hex}", secret_key="sk-lf-test", base_url="http://127.0.0.1:9",
                               tracer_provider=provider, span_exporter=exporter, flush_at=1)
    scores = []
    client.create_score = lambda **kw: scores.append(kw)  # no network: capture instead
    yield LangfuseTracer(client), exporter, scores
    provider.shutdown()


def attrs(span, key):
    return span.attributes.get(f"langfuse.observation.{key}")


def test_run_produces_one_trace_with_stage_spans_generations_and_scores(traced, tmp_path):
    tracer, exporter, scores = traced
    cfg = RunConfig(seed=Seed("test", "test seed", {"hackernews": ["hydroponics"]}), sources=["hackernews"],
                    out_dir=tmp_path)
    llm = LLMClient(FakeBackend(respond, cost=0.002), Budget(1.0, 10), tracer=tracer)
    result = asyncio.run(run(cfg, llm, transport=json_transport({"hn.algolia.com": HN}),
                             now=datetime(2026, 11, 25, tzinfo=UTC)))
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert {"inventor.run", "harvest", "search.hackernews", "extract", "extract.batch", "group", "score"} <= set(spans)
    assert len({s.context.trace_id for s in exporter.get_finished_spans()}) == 1  # one run = one trace

    gen = spans["extract.batch"]
    assert attrs(gen, "type") == "generation"
    assert json.loads(attrs(gen, "cost_details")) == {"total": 0.002}
    assert attrs(spans["search.hackernews"], "type") == "retriever"
    assert spans["extract.batch"].parent.span_id == spans["extract"].context.span_id

    names = {s["name"] for s in scores}
    # Per-call quality scores on the generation, and run health on the trace.
    assert {"candidates", "quote_verified_rate", "off_topic"} <= names
    assert {"quote_verified_rate", "off_topic_rate", "spend_usd", "health"} <= names
    health = next(s for s in scores if s["name"] == "health")
    assert health["value"] in ("ok", "warn") and health["data_type"] == "CATEGORICAL"
    assert result.metrics["spend_usd"] == pytest.approx(0.004)


def test_llm_errors_are_marked_on_the_generation(traced):
    from inventor.llm import LLMError, LLMRequest

    tracer, exporter, _ = traced

    class Broken:
        name = "broken"

        async def complete(self, request):
            raise LLMError("model said no")

    llm = LLMClient(Broken(), Budget(1.0, 10), tracer=tracer)
    with pytest.raises(LLMError):
        asyncio.run(llm.complete(LLMRequest(system="s", prompt="p", model="m"), name="x"))
    tracer.flush()
    [span] = exporter.get_finished_spans()
    assert attrs(span, "level") == "ERROR" and "model said no" in attrs(span, "status_message")


def test_null_tracer_is_default_and_harmless():
    llm = LLMClient(FakeBackend(lambda r: {"ok": 1}), Budget(1.0, 10))
    assert isinstance(llm.tracer, Tracer) and not llm.tracer.enabled
    from inventor.llm import LLMRequest
    r = asyncio.run(llm.complete(LLMRequest(system="s", prompt="p", model="m")))
    assert r.trace_id is None


def test_env_file_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nINV_A=from_file\nINV_B=from_file\nINV_EMPTY=\n")
    monkeypatch.setenv("INV_A", "already")
    monkeypatch.delenv("INV_B", raising=False)
    load_env_file(str(env))
    import os
    assert os.environ["INV_A"] == "already" and os.environ["INV_B"] == "from_file"
    assert "INV_EMPTY" not in os.environ
