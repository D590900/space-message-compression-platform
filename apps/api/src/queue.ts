import {
  context,
  isSpanContextValid,
  trace,
  type Context,
} from "@opentelemetry/api";
import { Redis } from "ioredis";

export class JobQueue {
  private readonly redis: Redis;

  public constructor(url: string) {
    this.redis = new Redis(url, {
      enableAutoPipelining: true,
      maxRetriesPerRequest: 2,
      lazyConnect: true,
    });
  }

  public async ready(): Promise<boolean> {
    if (this.redis.status === "wait") await this.redis.connect();
    return (await this.redis.ping()) === "PONG";
  }

  public async publishCompression(
    jobId: string,
    tenantSubject: string,
    requestId?: string,
  ): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    await this.redis.xadd(
      "smcp:compression-jobs",
      "*",
      "job_id",
      jobId,
      "tenant_subject",
      tenantSubject,
      ...queueCorrelationFields(requestId),
    );
  }

  public async publishDecompression(
    jobId: string,
    tenantSubject: string,
    requestId?: string,
  ): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    await this.redis.xadd(
      "smcp:decompression-jobs",
      "*",
      "decompression_id",
      jobId,
      "tenant_subject",
      tenantSubject,
      ...queueCorrelationFields(requestId),
    );
  }

  public async publishCapsule(
    capsuleId: string,
    tenantSubject: string,
    requestId?: string,
  ): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    await this.redis.xadd(
      "smcp:capsule-jobs",
      "*",
      "capsule_id",
      capsuleId,
      "tenant_subject",
      tenantSubject,
      ...queueCorrelationFields(requestId),
    );
  }

  public async close(): Promise<void> {
    if (this.redis.status !== "end") await this.redis.quit();
  }
}

export function queueCorrelationFields(
  requestId: string | undefined,
  activeContext: Context = context.active(),
): string[] {
  const fields = requestId ? ["request_id", requestId] : [];
  const spanContext = trace.getSpanContext(activeContext);
  if (!spanContext || !isSpanContextValid(spanContext)) return fields;
  fields.push(
    "traceparent",
    `00-${spanContext.traceId}-${spanContext.spanId}-${spanContext.traceFlags
      .toString(16)
      .padStart(2, "0")}`,
  );
  const traceState = spanContext.traceState?.serialize();
  if (traceState) fields.push("tracestate", traceState);
  return fields;
}
