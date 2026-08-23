import { describe, expect, it, vi } from "vitest";

import type {
  Database,
  JobOutboxClaim,
  JobOutboxReconciliationCandidate,
} from "../src/database.js";
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
const candidate: JobOutboxReconciliationCandidate = {
  tenant_subject: "org_test",
  project_id: "1bf62607-6fa8-42f8-a6f1-a660397b36cf",
  topic: "compression.requested",
  aggregate_id: event.aggregate_id,
};

describe("job outbox publisher", () => {
  it("publishes a claimed event and marks it complete", async () => {
    const claimJobOutboxEvents = vi.fn(() => Promise.resolve([event]));
    const completeJobOutboxEvent = vi.fn(() => Promise.resolve());
    const failJobOutboxEvent = vi.fn(() => Promise.resolve());
    const findJobOutboxReconciliationCandidates = vi.fn(() =>
      Promise.resolve([]),
    );
    const publishCompression = vi.fn(() => Promise.resolve());
    const publisher = new JobOutboxPublisher(
      {
        claimJobOutboxEvents,
        completeJobOutboxEvent,
        failJobOutboxEvent,
        findJobOutboxReconciliationCandidates,
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
    expect(findJobOutboxReconciliationCandidates).toHaveBeenCalledWith(
      1_800_000,
      50,
    );
  });

  it("releases failed claims with a redacted error class", async () => {
    const failure = new Error("redis://secret@internal:6379");
    failure.name = "RedisUnavailable";
    const failJobOutboxEvent = vi.fn(() => Promise.resolve());
    const publisher = new JobOutboxPublisher(
      {
        findJobOutboxReconciliationCandidates: () => Promise.resolve([]),
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
    const findJobOutboxReconciliationCandidates = vi.fn(() =>
      Promise.resolve([candidate]),
    );
    const enqueueReconciledJobOutboxEvent = vi.fn(() => Promise.resolve(true));
    const hasJobDelivery = vi.fn(() => Promise.resolve(true));
    const claimJobOutboxEvents = vi.fn(() => Promise.resolve([]));
    const publisher = new JobOutboxPublisher(
      {
        findJobOutboxReconciliationCandidates,
        enqueueReconciledJobOutboxEvent,
        claimJobOutboxEvents,
      } as unknown as Database,
      { hasJobDelivery } as unknown as JobQueue,
      250,
      60_000,
      1_800_000,
    );

    await publisher.poll();
    await publisher.poll();

    expect(findJobOutboxReconciliationCandidates).toHaveBeenCalledTimes(1);
    expect(hasJobDelivery).toHaveBeenCalledWith(
      candidate.topic,
      candidate.aggregate_id,
    );
    expect(enqueueReconciledJobOutboxEvent).not.toHaveBeenCalled();
    expect(claimJobOutboxEvents).toHaveBeenCalledTimes(2);
  });

  it("re-enqueues a stale PostgreSQL job only when its Valkey marker is absent", async () => {
    const enqueueReconciledJobOutboxEvent = vi.fn(() => Promise.resolve(true));
    const publisher = new JobOutboxPublisher(
      {
        findJobOutboxReconciliationCandidates: () =>
          Promise.resolve([candidate]),
        enqueueReconciledJobOutboxEvent,
        claimJobOutboxEvents: () => Promise.resolve([]),
      } as unknown as Database,
      {
        hasJobDelivery: () => Promise.resolve(false),
      } as unknown as JobQueue,
      250,
      60_000,
      1_800_000,
    );

    await publisher.poll();

    expect(enqueueReconciledJobOutboxEvent).toHaveBeenCalledWith(
      candidate,
      1_800_000,
    );
  });
});
