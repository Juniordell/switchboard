"""Tracing, vendor-neutral, with Langfuse as an endpoint rather than a
dependency.

**No Langfuse code anywhere.** Langfuse accepts OTLP over HTTP, so the whole
integration is the standard `OTLPSpanExporter` pointed at their ingest URL
with a basic-auth header built from the keys. Nothing here imports their
SDK, and swapping them for any other OTLP backend is one environment
variable. That is a stronger version of "do not couple to their SDK beyond
the exporter": we do not use their exporter either.

**One trace across the call and the pipeline that follows it.**
`docs/ARCHITECTURE.md` asks for a single trace spanning the phone call and
the async agents that ran afterwards - but those are different processes,
minutes apart, and OpenTelemetry context does not survive either gap on its
own. So the call's `traceparent` is written to `ops.calls`, and the worker
restores it before it starts: the extraction and review spans are children
of the call span, in the same trace, even though the call ended first.

Attributes follow the OpenTelemetry **GenAI semantic conventions**
(`gen_ai.*`) rather than names of our own, so the spans mean the same thing
to any backend that reads them.
"""

import base64
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as gen_ai
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

log = logging.getLogger(__name__)

SERVICE_NAME = "switchboard"

#: Langfuse's OTLP ingest path. Only used to build a URL; nothing here
#: knows anything else about them.
LANGFUSE_OTLP_PATH = "/api/public/otel/v1/traces"

_propagator = TraceContextTextMapPropagator()
_provider: TracerProvider | None = None


def _endpoint_and_headers() -> tuple[str, dict[str, str]] | None:
    """Where to send spans, or `None` if nothing is configured.

    `OTEL_EXPORTER_OTLP_ENDPOINT` wins, so any OTLP backend works without
    touching this file. Langfuse is the fallback because it is what the
    project happens to use.
    """
    generic = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if generic:
        return generic.rstrip("/") + "/v1/traces", {}

    host = os.environ.get("LANGFUSE_HOST", "").strip()
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not (host and public and secret):
        return None

    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return host.rstrip("/") + LANGFUSE_OTLP_PATH, {"Authorization": f"Basic {token}"}


def tracer_provider(service: str = SERVICE_NAME) -> TracerProvider:
    """The process's provider. Built once, exports only if configured.

    With nothing configured it still records spans and drops them, so the
    instrumentation is exercised on every developer machine rather than
    only where credentials exist - an attribute that is wrong is wrong
    whether or not anyone is collecting it.
    """
    global _provider
    if _provider is not None:
        return _provider

    _provider = TracerProvider(resource=Resource.create({"service.name": service}))
    target = _endpoint_and_headers()
    if target is None:
        log.info("tracing on, exporting nowhere: no OTLP endpoint configured")
    else:
        endpoint, headers = target
        _provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        )
        log.info("tracing to %s", endpoint)

    trace.set_tracer_provider(_provider)
    return _provider


def tracer(name: str = SERVICE_NAME):
    return tracer_provider().get_tracer(name)


def current_traceparent() -> str | None:
    """The active span as a W3C `traceparent`, for storing somewhere.

    This is what carries the trace across the gap between a call ending and
    the worker reading it minutes later in another process.
    """
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


@contextmanager
def continue_trace(traceparent: str | None) -> Iterator[None]:
    """Re-enter a trace recorded earlier, by another process.

    A missing or malformed `traceparent` starts a fresh trace rather than
    failing: a call that was not traced must still be extractable.
    """
    if not traceparent:
        yield
        return

    parent = _propagator.extract({"traceparent": traceparent})
    token = otel_context.attach(parent)
    try:
        yield
    finally:
        otel_context.detach(token)


@contextmanager
def genai_span(
    name: str,
    *,
    operation: str,
    model: str | None = None,
    call_id: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """A span named and attributed per the GenAI semantic conventions.

    `gen_ai.conversation.id` carries the call id, which is what makes every
    span from one phone call - the turns, the tools, the extraction, the
    review - findable together in any backend.
    """
    attrs: dict[str, Any] = {gen_ai.GEN_AI_OPERATION_NAME: operation}
    if model:
        attrs[gen_ai.GEN_AI_REQUEST_MODEL] = model
    if call_id:
        attrs[gen_ai.GEN_AI_CONVERSATION_ID] = call_id
    if attributes:
        attrs.update(attributes)

    with tracer().start_as_current_span(name, attributes=attrs) as span:
        yield span


def record_usage(span: trace.Span, usage: dict[str, Any] | None) -> None:
    """Token counts, under the conventional names."""
    if not usage:
        return
    if "prompt_tokens" in usage:
        span.set_attribute(gen_ai.GEN_AI_USAGE_INPUT_TOKENS, usage["prompt_tokens"])
    if "completion_tokens" in usage:
        span.set_attribute(
            gen_ai.GEN_AI_USAGE_OUTPUT_TOKENS, usage["completion_tokens"]
        )
