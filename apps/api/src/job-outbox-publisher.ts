import { randomUUID } from "node:crypto";

import type { Database, JobOutboxClaim } from "./database.js";
import type { JobQueue } from "./queue.js";

export interface JobOutboxPublisherGateway {
  start(): void;
  close(): Promise<void>;
}

export class JobOutboxPublisher implements JobOutboxPublisherGateway {
  private timer: NodeJS.Timeout | undefined;
  private running = false;

  public constructor(
    private readonly database: Database,
    private readonly queue: JobQueue,
    private readonly pollMilliseconds: number,
  ) {}

  public start(): void {
    if (this.timer) return;
    this.timer = setInterval(
      () =>
        void this.poll().catch((error: unknown) => {
          const errorCode =
            error instanceof Error ? error.name : "unknown_error";
          console.error("job outbox publisher poll failed", { errorCode });
        }),
      this.pollMilliseconds,
    );
    this.timer.unref();
  }

  public async close(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
    while (this.running)
      await new Promise((resolve) => setTimeout(resolve, 10));
  }

  public async poll(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      const claimToken = randomUUID();
      const events = await this.database.claimJobOutboxEvents(claimToken, 50);
      for (const event of events) await this.publish(event, claimToken);
    } finally {
      this.running = false;
    }
  }

  private async publish(
    event: JobOutboxClaim,
    claimToken: string,
  ): Promise<void> {
    const requestId =
      typeof event.payload.request_id === "string"
        ? event.payload.request_id
        : undefined;
    try {
      if (event.topic === "compression.requested") {
        await this.queue.publishCompression(
          event.aggregate_id,
          event.tenant_subject,
          requestId,
        );
      } else if (event.topic === "decompression.requested") {
        await this.queue.publishDecompression(
          event.aggregate_id,
          event.tenant_subject,
          requestId,
        );
      } else if (event.topic === "capsule.requested") {
        await this.queue.publishCapsule(
          event.aggregate_id,
          event.tenant_subject,
          requestId,
        );
      } else {
        throw new Error("unsupported_job_outbox_topic");
      }
      await this.database.completeJobOutboxEvent(event.id, claimToken);
    } catch (error) {
      const errorCode = error instanceof Error ? error.name : "unknown_error";
      await this.database.failJobOutboxEvent(
        event.id,
        claimToken,
        event.attempt,
        errorCode,
      );
    }
  }
}
