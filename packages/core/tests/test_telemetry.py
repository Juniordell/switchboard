"""Tracing: the trace that has to survive a process boundary, the GenAI
attribute names, and the promise that Langfuse is an endpoint and not a
dependency.

Nothing here sends a span anywhere. The exporter's configuration is
asserted by building it, which is the part that can be wrong; whether
Langfuse accepts it is their side of an open protocol.
"""

import base64
import pathlib

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import switchboard_core.telemetry as tel

REPO = pathlib.Path(__file__).parents[3]


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    tel.tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.clear()


class TestOneTraceAcrossTheBoundary:
    def test_a_traceparent_round_trips_into_the_same_trace(self, spans) -> None:
        """The call ends, the worker starts minutes later in another
        process, and both belong to one trace. OpenTelemetry context
        survives neither gap on its own - this is what carries it."""
        with tel.genai_span("call", operation="invoke_agent", call_id="c1"):
            carried = tel.current_traceparent()

        with tel.continue_trace(carried):
            with tel.genai_span("extract", operation="invoke_agent", call_id="c1"):
                pass
            with tel.genai_span("review", operation="invoke_agent", call_id="c1"):
                pass

        finished = spans.get_finished_spans()
        assert {s.context.trace_id for s in finished} == {
            finished[0].context.trace_id
        }, "the pipeline started its own trace"

    def test_the_pipeline_hangs_off_the_call_span(self, spans) -> None:
        with tel.genai_span("call", operation="invoke_agent", call_id="c2") as call:
            carried = tel.current_traceparent()
            call_span_id = call.get_span_context().span_id
        with (
            tel.continue_trace(carried),
            tel.genai_span("extract", operation="invoke_agent", call_id="c2"),
        ):
            pass

        extract = next(s for s in spans.get_finished_spans() if s.name == "extract")
        assert extract.parent is not None
        assert extract.parent.span_id == call_span_id

    def test_an_untraced_call_still_runs(self, spans) -> None:
        """A call recorded before tracing existed has no traceparent. The
        worker must extract it anyway, in a trace of its own."""
        with (
            tel.continue_trace(None),
            tel.genai_span("extract", operation="invoke_agent", call_id="c3"),
        ):
            pass
        assert spans.get_finished_spans()


class TestTheAttributesAreTheConventionalOnes:
    def test_it_uses_gen_ai_names(self, spans) -> None:
        with tel.genai_span(
            "chat", operation="chat", model="gpt-4o-mini", call_id="c4"
        ):
            pass
        attrs = spans.get_finished_spans()[0].attributes
        assert attrs["gen_ai.operation.name"] == "chat"
        assert attrs["gen_ai.request.model"] == "gpt-4o-mini"
        assert attrs["gen_ai.conversation.id"] == "c4"

    def test_the_call_id_is_the_conversation_id(self, spans) -> None:
        """What makes every span from one phone call findable together in
        any backend, without a vendor's grouping concept."""
        with tel.genai_span("a", operation="execute_tool", call_id="call_x"):
            pass
        with tel.genai_span("b", operation="invoke_agent", call_id="call_x"):
            pass
        ids = {
            s.attributes["gen_ai.conversation.id"] for s in spans.get_finished_spans()
        }
        assert ids == {"call_x"}

    def test_usage_lands_under_the_conventional_keys(self, spans) -> None:
        with tel.genai_span("chat", operation="chat") as span:
            tel.record_usage(span, {"prompt_tokens": 120, "completion_tokens": 40})
        attrs = spans.get_finished_spans()[0].attributes
        assert attrs["gen_ai.usage.input_tokens"] == 120
        assert attrs["gen_ai.usage.output_tokens"] == 40


class TestLangfuseIsAnEndpointNotADependency:
    def test_no_module_of_ours_imports_langfuse(self) -> None:
        """The constraint, checked rather than promised. Langfuse speaks
        OTLP, so the whole integration is a URL and a header."""
        offenders = []
        for root in ("packages/core/src", "apps/api/src", "apps/agent/src"):
            for path in (REPO / root).rglob("*.py"):
                body = path.read_text()
                if "import langfuse" in body or "from langfuse" in body:
                    offenders.append(str(path.relative_to(REPO)))
        assert offenders == []

    def test_it_builds_langfuse_basic_auth_from_the_keys(self, monkeypatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        endpoint, headers = tel._endpoint_and_headers()
        assert endpoint == "https://cloud.langfuse.com/api/public/otel/v1/traces"
        expected = base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_any_otlp_backend_wins_over_langfuse(self, monkeypatch) -> None:
        """Swapping vendors is one environment variable, which is what
        makes this an endpoint rather than a coupling."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        endpoint, headers = tel._endpoint_and_headers()
        assert endpoint == "http://collector:4318/v1/traces"
        assert headers == {}

    def test_nothing_configured_still_records(self, monkeypatch) -> None:
        """Instrumentation runs on every machine, so a wrong attribute is
        wrong whether or not anyone is collecting it."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
        assert tel._endpoint_and_headers() is None
