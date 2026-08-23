import { describe, expect, it, vi } from "vitest";

import type { Database, JobOutboxClaim } from "../src/database.js";
import { JobOutboxPublisher } from "../src/job-outbox-publisher.js";
import type { JobQueue } from "../src/queue.js";

const event: JobOutboxClaim = {
  id: "outbox-1",
  tenant_subject: "org_test",
  topic: "compression.requested",
  aggregate_id: "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
  payload: { request_id: "request-123" },
  attempt: 1,
};

describe("job outbox publisher", () => {
  it("publishes a claimed event and marks it complete", async () => {
    const claimJobOutboxEvents = vi.fn(() => Promise.resolve([event]));
    const completeJobOutboxEvent = vi.fn(() => Promise.resolve());
    const failJobOutboxEvent = vi.fn(() => Promise.resolve());
    const reconcileJobOutboxEvents = vi.fn(() => Promise.resolve(0));
    const publishCompression = vi.fn(() => Promise.resolve());
    const publisher = new JobOutboxPublisher(
      {
        claimJobOutboxEvents,
        completeJobOutboxEvent,
        failJobOutboxEvent,
        reconcileJobOutboxEvents,
      } as unknown as Database,
      { publishCompression } as unknown as JobQueue,
      250,
      60_000,
      1_800_000,
    );

    await publisher.poll();

    expect(publishCompression).toHaveBeenCalledWith(
      event.aggregate_id,
      "org_test",
      "request-123",
    );
    expect(completeJobOutboxEvent).toHaveBeenCalledWith(
      "outbox-1",
      expect.any(String),
    );
    expect(failJobOutboxEvent).not.toHaveBeenCalled();
    expect(reconcileJobOutboxEvents).toHaveBeenCalledWith(1_800_000);
  });

  it("releases failed claims with a redacted error class", async () => {
    const failure = new Error("redis://secret@internal:6379");
    failure.name = "RedisUnavailable";
    const failJobOutboxEvent = vi.fn(() => Promise.resolve());
    const publisher = new JobOutboxPublisher(
      {
        reconcileJobOutboxEvents: () => Promise.resolve(0),
        claimJobOutboxEvents: () => Promise.resolve([event]),
        completeJobOutboxEvent: vi.fn(() => Promise.resolve()),
        failJobOutboxEvent,
      } as unknown as Database,
      {
        publishCompression: vi.fn(() => Promise.reject(failure)),
      } as unknown as JobQueue,
      250,
      60_000,
      1_800_000,
    );

    await publisher.poll();

    expect(failJobOutboxEvent).toHaveBeenCalledWith(
      "outbox-1",
      expect.any(String),
      1,
      "RedisUnavailable",
    );
    expect(JSON.stringify(failJobOutboxEvent.mock.calls)).not.toContain(
      "redis://secret",
    );
  });

  it("reconciles at the configured cadence", async () => {
    const reconcileJobOutboxEvents = vi.fn(() => Promise.resolve(2));
    const claimJobOutboxEvents = vi.fn(() => Promise.resolve([]));
    const publisher = new JobOutboxPublisher(
      {
        reconcileJobOutboxEvents,
        claimJobOutboxEvents,
      } as unknown as Database,
      {} as JobQueue,
      250,
      60_000,
      1_800_000,
    );

    await publisher.poll();
    await publisher.poll();

    expect(reconcileJobOutboxEvents).toHaveBeenCalledTimes(1);
    expect(claimJobOutboxEvents).toHaveBeenCalledTimes(2);
  });
});
