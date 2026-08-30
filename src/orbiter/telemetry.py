"""OpenTelemetry wiring — one distributed trace per job, across the async gap.

The interesting problem: a job's life spans three PROCESSES separated by a
database table and a message broker. HTTP tracing gets you the API span for
free; the value is stitching the rest — so the trace context (W3C
``traceparent``) travels IN the data:

    API submit ──▶ outbox row carries {"traceparent": ...}
                     └─▶ relay extracts it, publishes with NATS headers
                           └─▶ worker extracts from headers, executes

One trace: submit → publish → (redeliveries) → execution → completion.

Everything here is a no-op unless ORBITER_OTEL_ENDPOINT is set: unit tests,
local scripts, and CI never need a collector running.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject

_INITIALIZED = False


def init_telemetry(service_name: str, endpoint: str) -> None:
    """Install real providers exporting OTLP/HTTP to ``endpoint``.

    Call once at process start. With an empty endpoint this does nothing and
    the API's no-op defaults stay in place.
    """
    global _INITIALIZED
    if not endpoint or _INITIALIZED:
        return
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
                export_interval_millis=10_000,
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)
    _INITIALIZED = True


def tracer() -> trace.Tracer:
    return trace.get_tracer("orbiter")


def meter() -> metrics.Meter:
    return metrics.get_meter("orbiter")


def current_carrier() -> dict[str, str]:
    """The active trace context as a plain dict, ready to ride inside a JSON
    payload or a NATS header block. Empty when tracing is off."""
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


def context_from(carrier: dict[str, Any] | None) -> Context:
    """Rebuild a trace context from a carrier dict (or none: fresh context)."""
    return extract({k: str(v) for k, v in (carrier or {}).items()})
