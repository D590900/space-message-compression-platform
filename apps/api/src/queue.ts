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
  ): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    await this.redis.xadd(
      "smcp:compression-jobs",
      "*",
      "job_id",
      jobId,
      "tenant_subject",
      tenantSubject,
    );
  }

  public async publishDecompression(
    jobId: string,
    tenantSubject: string,
  ): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    await this.redis.xadd(
      "smcp:decompression-jobs",
      "*",
      "decompression_id",
      jobId,
      "tenant_subject",
      tenantSubject,
    );
  }

  public async close(): Promise<void> {
    if (this.redis.status !== "end") await this.redis.quit();
  }
}
