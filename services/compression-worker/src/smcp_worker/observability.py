from __future__ import annotations

from collections.abc import Callable
from threading import Event

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

from smcp_worker.settings import Settings

READINESS = Event()

JOBS = Counter("jobs", "Worker messages processed.", ("job_type", "outcome"))
JOBS_FAILED = Counter("jobs_failed", "Worker messages that raised an exception.", ("job_type",))
QUEUE_DEPTH = Gauge("queue_depth", "Current Valkey stream length.", ("queue",))
JOB_DURATION = Histogram(
    "job_duration_seconds",
    "Worker message processing duration.",
    ("job_type",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)
ENCODE_DURATION = Histogram(
    "encode_duration_seconds",
    "Candidate generation duration.",
    ("content_type",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)
DECODE_DURATION = Histogram(
    "decode_duration_seconds",
    "Artifact decode duration.",
    ("codec_id",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 30),
)
INPUT_BYTES = Counter("input_bytes", "Validated source bytes.", ("content_type",))
OUTPUT_BYTES = Counter("output_bytes", "Selected compressed payload bytes.", ("content_type",))
COMPRESSION_RATIO = Histogram(
    "compression_ratio",
    "Source bytes divided by selected payload bytes.",
    ("content_type",),
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
)
QUALITY_GATE_FAILURES = Counter(
    "quality_gate_failures", "Inputs with no passing candidate.", ("content_type",)
)
GPU_UTILIZATION = Gauge(
    "gpu_utilization", "GPU utilization ratio; zero for the CPU image.", ("device",)
)
WORKER_OOM = Counter("worker_oom", "Worker MemoryError events.")
CAPSULE_FILL_RATIO = Histogram(
    "capsule_fill_ratio",
    "Final capsule bytes divided by configured budget.",
    buckets=(0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0),
)

GPU_UTILIZATION.labels(device="cpu").set(0)


def configure_tracing(settings: Settings) -> Callable[[], None]:
    if settings.otel_exporter_otlp_traces_endpoint is None:
        return lambda: None
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.version": "0.1.0",
                "deployment.environment.name": settings.environment,
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_traces_endpoint))
    )
    trace.set_tracer_provider(provider)
    return provider.shutdown
