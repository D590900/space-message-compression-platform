import { context, TraceFlags, trace } from "@opentelemetry/api";
import { describe, expect, it } from "vitest";

import { jobDeliveryMarkerKey, queueCorrelationFields } from "../src/queue.js";

describe("queue correlation", () => {
  it("injects a valid W3C parent and request ID without baggage", () => {
    const active = trace.setSpanContext(context.active(), {
      traceId: "4bf92f3577b34da6a3ce929d0e0e4736",
      spanId: "00f067aa0ba902b7",
      traceFlags: TraceFlags.SAMPLED,
      isRemote: false,
    });

    expect(queueCorrelationFields("request-123", active)).toEqual([
      "request_id",
      "request-123",
      "traceparent",
      "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    ]);
  });

  it("does not emit an invalid trace context", () => {
    const invalid = trace.setSpanContext(context.active(), {
      traceId: "0".repeat(32),
      spanId: "0".repeat(16),
      traceFlags: TraceFlags.NONE,
      isRemote: false,
    });
    expect(queueCorrelationFields("request-123", invalid)).toEqual([
      "request_id",
      "request-123",
    ]);
  });

  it("uses a topic-and-aggregate delivery marker", () => {
    expect(
      jobDeliveryMarkerKey(
        "compression.requested",
        "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
      ),
    ).toBe(
      "smcp:job-delivery:compression.requested:85bd5e09-a8fb-4d2c-a560-5d2365badf84",
    );
  });
});
