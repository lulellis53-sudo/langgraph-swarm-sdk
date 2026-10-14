"""OpenTelemetry setup, kept separate from LangSmith tracing.

LangSmith covers LLM-specific traces through ``LANGSMITH_*`` variables; this
module installs a general OpenTelemetry TracerProvider for spans that any
OTel-compatible backend can consume. Swap the ConsoleSpanExporter for an OTLP
exporter to forward spans to a collector.
"""


def setup_telemetry(service_name: str = "langswarm"):
    """Install a global OpenTelemetry TracerProvider with a console exporter."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider
