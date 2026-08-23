import {
  context,
  isSpanContextValid,
  trace,
  type Context,
} from "@opentelemetry/api";
import { Redis } from "ioredis";

const PUBLISH_JOB_SCRIPT = `
local message_id = redis.call('XADD', KEYS[1], '*', unpack(ARGV))
redis.call('SADD', KEYS[2], message_id)
return message_id
`;

export function jobDeliveryMarkerKey(
  topic: string,
  aggregateId: string,
): string {
  return `smcp:job-delivery:${topic}:${aggregateId}`;
}

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
    await this.publish(
      "smcp:compression-jobs",
      "compression.requested",
      jobId,
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
    await this.publish(
      "smcp:decompression-jobs",
      "decompression.requested",
      jobId,
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
    await this.publish(
      "smcp:capsule-jobs",
      "capsule.requested",
      capsuleId,
      "capsule_id",
      capsuleId,
      "tenant_subject",
      tenantSubject,
      ...queueCorrelationFields(requestId),
    );
  }

  public async hasJobDelivery(
    topic: string,
    aggregateId: string,
  ): Promise<boolean> {
    if (this.redis.status === "wait") await this.redis.connect();
    return (
      (await this.redis.exists(jobDeliveryMarkerKey(topic, aggregateId))) === 1
    );
  }

  private async publish(
    stream: string,
    topic: string,
    aggregateId: string,
    ...fields: string[]
  ): Promise<void> {
    await this.redis.eval(
      PUBLISH_JOB_SCRIPT,
      2,
      stream,
      jobDeliveryMarkerKey(topic, aggregateId),
      ...fields,
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
