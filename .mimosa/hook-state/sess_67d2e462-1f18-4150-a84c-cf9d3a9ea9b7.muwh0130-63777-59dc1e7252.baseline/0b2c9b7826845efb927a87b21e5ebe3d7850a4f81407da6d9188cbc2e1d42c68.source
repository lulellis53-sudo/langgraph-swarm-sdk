"""LangChain, Prometheus, and OpenTelemetry collectors for the agent suite.

Token totals stamped on scripted replies are local tokenizer counts. They are
not provider usage. Prometheus uses a private registry. OpenTelemetry uses an
in-memory exporter and does not replace the process-wide provider.
"""

from __future__ import annotations

import gc
import resource
import sys
import threading
import time
from typing import Any

from benchmark.tests.fakes import Script, ScriptedModel, answer
from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models.chat_models import Callbacks
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult, LLMResult

from swarm_sdk.prompting.budget import count_text


class BenchCallbackHandler(BaseCallbackHandler):
    """Count chat-model and tool callback events. Safe to share across threads."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_starts = 0
        self.llm_ends = 0
        self.llm_errors = 0
        self.tool_starts = 0
        self.tool_ends = 0
        self.callback_samples_ms: list[float] = []
        self._open: dict[str, int] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        """Record one chat-model start."""
        del serialized, messages
        run_id = str(kwargs.get("run_id", ""))
        with self._lock:
            self.llm_starts += 1
            self._open[run_id] = time.perf_counter_ns()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Record one model end and its callback duration."""
        del response
        run_id = str(kwargs.get("run_id", ""))
        with self._lock:
            self.llm_ends += 1
            started = self._open.pop(run_id, None)
            if started is not None:
                self.callback_samples_ms.append((time.perf_counter_ns() - started) / 1e6)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        """Record one model error."""
        del error
        run_id = str(kwargs.get("run_id", ""))
        with self._lock:
            self.llm_errors += 1
            self._open.pop(run_id, None)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Record one tool start."""
        del serialized, input_str, kwargs
        with self._lock:
            self.tool_starts += 1

    def on_tool_end(self, output: object, **kwargs: Any) -> None:
        """Record one tool end."""
        del output, kwargs
        with self._lock:
            self.tool_ends += 1

    def reset(self) -> None:
        """Drop warmup events so the report counts measured samples only."""
        with self._lock:
            self.llm_starts = 0
            self.llm_ends = 0
            self.llm_errors = 0
            self.tool_starts = 0
            self.tool_ends = 0
            self.callback_samples_ms = []
            self._open.clear()


class MeteredScriptedModel(ScriptedModel):
    """Scripted chat model that stamps tokenizer usage for LangChain callbacks."""

    meter_model_name: str = "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        message = result.generations[0].message
        prompt = "\n".join(_content_text(item) for item in messages)
        reply = _content_text(message)
        prompt_tokens = count_text(prompt)
        completion_tokens = count_text(reply)
        message.usage_metadata = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        message.response_metadata = {"model_name": self.meter_model_name}
        return result


def _content_text(message: object) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


class _Prometheus:
    def __init__(self) -> None:
        self.available = False
        self._build()

    def _build(self) -> None:
        try:
            from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
        except ImportError:
            self.available = False
            self.registry = None
            return
        self.available = True
        self.registry = CollectorRegistry()
        self.steps = Counter(
            "agent_suite_steps_total",
            "Counted agent-task steps.",
            ["mode", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "agent_suite_step_latency_seconds",
            "Counted step wall time.",
            ["mode"],
            registry=self.registry,
        )
        self.tokens = Counter(
            "agent_suite_prompt_tokens_total",
            "Tokenizer prompt tokens on counted steps.",
            ["mode"],
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "agent_suite_in_flight",
            "Peak in-flight steps observed in a counted pass.",
            ["mode"],
            registry=self.registry,
        )

    def reset(self) -> None:
        """Replace the registry so warmup observations are not exported."""
        self._build()

    def observe(self, mode: str, status: str, seconds: float, prompt_tokens: int) -> None:
        if not self.available:
            return
        self.steps.labels(mode=mode, status=status).inc()
        self.latency.labels(mode=mode).observe(max(0.0, seconds))
        if prompt_tokens > 0:
            self.tokens.labels(mode=mode).inc(prompt_tokens)

    def set_in_flight(self, mode: str, peak: int) -> None:
        if self.available:
            self.in_flight.labels(mode=mode).set(peak)

    def report(self) -> dict[str, object]:
        if not self.available or self.registry is None:
            return {"available": False}
        samples: list[dict[str, object]] = []
        steps_total = 0.0
        latency_sum: dict[str, float] = {}
        latency_count: dict[str, float] = {}
        prompt_tokens: dict[str, float] = {}
        in_flight: dict[str, float] = {}
        for metric in self.registry.collect():
            for sample in metric.samples:
                samples.append(
                    {
                        "name": sample.name,
                        "labels": dict(sample.labels),
                        "value": sample.value,
                    }
                )
                labels = sample.labels
                mode = str(labels.get("mode", ""))
                if sample.name == "agent_suite_steps_total":
                    steps_total += sample.value
                elif sample.name == "agent_suite_step_latency_seconds_sum":
                    latency_sum[mode] = sample.value
                elif sample.name == "agent_suite_step_latency_seconds_count":
                    latency_count[mode] = sample.value
                elif sample.name == "agent_suite_prompt_tokens_total":
                    prompt_tokens[mode] = sample.value
                elif sample.name == "agent_suite_in_flight":
                    in_flight[mode] = sample.value
        return {
            "available": True,
            "steps_total": steps_total,
            "latency_seconds_sum": latency_sum,
            "latency_seconds_count": latency_count,
            "prompt_tokens_total": prompt_tokens,
            "in_flight_peak": in_flight,
            "samples": samples,
        }


class _OpenTelemetry:
    def __init__(self) -> None:
        self.available = False
        self.provider: object | None = None
        self.exporter: object | None = None
        self.tracer: object | None = None
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )
        except ImportError:
            return
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        self.provider = provider
        self.exporter = exporter
        self.tracer = provider.get_tracer("benchmark.agent_suite")
        self.available = True

    def reset(self) -> None:
        """Drop warmup spans."""
        clear = getattr(self.exporter, "clear", None)
        if callable(clear):
            clear()

    def span(self, name: str, **attributes: str | int | float | bool) -> object:
        if self.tracer is None:
            from contextlib import nullcontext

            return nullcontext()
        start = getattr(self.tracer, "start_as_current_span")
        return start(name, attributes=attributes)

    def shutdown(self) -> None:
        shutdown = getattr(self.provider, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def report(self) -> dict[str, object]:
        if not self.available or self.exporter is None:
            return {"available": False}
        finished = self.exporter.get_finished_spans()
        grouped: dict[tuple[str, str], list[float]] = {}
        errors = 0
        for span in finished:
            if _span_failed(span):
                errors += 1
            mode = str(getattr(span, "attributes", {}).get("mode", ""))
            start_ns = int(getattr(span, "start_time", 0) or 0)
            end_ns = int(getattr(span, "end_time", 0) or 0)
            grouped.setdefault((str(span.name), mode), []).append((end_ns - start_ns) / 1e6)
        rows = [
            {
                "name": name,
                "mode": mode,
                "count": len(durations),
                "p50_ms": _median(durations),
                "p95_ms": _nearest(durations, 0.95),
                "p99_ms": _nearest(durations, 0.99),
            }
            for (name, mode), durations in sorted(grouped.items())
        ]
        return {
            "available": True,
            "span_count": len(finished),
            "error_spans": errors,
            "spans": rows,
        }


def _span_failed(span: object) -> bool:
    status = getattr(span, "status", None)
    code = getattr(status, "status_code", None)
    name = getattr(code, "name", "")
    return name == "ERROR"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    mid = count // 2
    if count % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _nearest(values: list[float], fraction: float) -> float:
    import math

    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = math.ceil(fraction * len(ordered)) - 1
    return ordered[max(0, index)]


class SuiteInstruments:
    """Collectors attached to counted agent steps."""

    def __init__(self) -> None:
        self.langchain = BenchCallbackHandler()
        self.usage = UsageMetadataCallbackHandler()
        self.prometheus = _Prometheus()
        self.otel = _OpenTelemetry()

    def make_model(self, model_name: str, reply: str) -> MeteredScriptedModel:
        """Build a scripted model that reports usage and callback events."""
        model = MeteredScriptedModel(
            script=Script([answer(reply)]),
            meter_model_name=model_name or "scripted",
        )
        callbacks: Callbacks = [self.usage, self.langchain]
        model.callbacks = callbacks
        return model

    def reset(self) -> None:
        """Clear warmup observations."""
        self.langchain.reset()
        self.usage = UsageMetadataCallbackHandler()
        self.prometheus.reset()
        self.otel.reset()

    def observe_step(self, mode: str, status: str, elapsed_ns: int, prompt_tokens: int) -> None:
        self.prometheus.observe(mode, status, elapsed_ns / 1e9, prompt_tokens)

    def set_in_flight(self, mode: str, peak: int) -> None:
        self.prometheus.set_in_flight(mode, peak)

    def span(self, name: str, **attributes: str | int | float | bool) -> object:
        return self.otel.span(name, **attributes)

    def shutdown(self) -> None:
        self.otel.shutdown()

    def langchain_report(self) -> dict[str, object]:
        """Return callback counts and tokenizer usage grouped by manifest model."""
        by_model: dict[str, dict[str, int]] = {}
        total = 0
        for model_name, metadata in self.usage.usage_metadata.items():
            row = {
                "input_tokens": int(metadata.get("input_tokens", 0)),
                "output_tokens": int(metadata.get("output_tokens", 0)),
                "total_tokens": int(metadata.get("total_tokens", 0)),
            }
            by_model[str(model_name)] = row
            total += row["total_tokens"]
        return {
            "llm_starts": self.langchain.llm_starts,
            "llm_ends": self.langchain.llm_ends,
            "llm_errors": self.langchain.llm_errors,
            "tool_starts": self.langchain.tool_starts,
            "tool_ends": self.langchain.tool_ends,
            "callback_samples_ms": list(self.langchain.callback_samples_ms),
            "usage_note": (
                "usage_by_model tokens are local tokenizer counts stamped on the "
                "scripted reply, not provider-reported usage"
            ),
            "usage_by_model": by_model,
            "total_tokens": total,
        }

    def prometheus_report(self) -> dict[str, object]:
        return self.prometheus.report()

    def otel_report(self) -> dict[str, object]:
        return self.otel.report()


def gc_collections() -> list[int]:
    """Return cumulative GC collection counts for generations 0, 1, and 2."""
    return [int(row["collections"]) for row in gc.get_stats()]


def rusage_snapshot() -> dict[str, float]:
    """Return process CPU time and context switches. RSS stays on the suite report."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "utime_s": float(usage.ru_utime),
        "stime_s": float(usage.ru_stime),
        "nvcsw": float(getattr(usage, "ru_nvcsw", 0)),
        "nivcsw": float(getattr(usage, "ru_nivcsw", 0)),
    }


def rusage_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """Subtract two :func:`rusage_snapshot` readings."""
    return {key: after[key] - before[key] for key in before}


def python_rss_bytes() -> int:
    """Peak RSS in bytes. macOS reports bytes; Linux reports KiB."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)
