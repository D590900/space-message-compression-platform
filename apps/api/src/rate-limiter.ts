import { createHash } from "node:crypto";

import { Redis } from "ioredis";

import { ApiProblem } from "./problem.js";

const WINDOW_SECONDS = 60;
const COUNTER_TTL_SECONDS = 120;
const CONSUME_SCRIPT = `
local tenant = redis.call('INCRBY', KEYS[1], ARGV[1])
local credential = redis.call('INCRBY', KEYS[2], ARGV[1])
if tenant == tonumber(ARGV[1]) then redis.call('EXPIRE', KEYS[1], ARGV[4]) end
if credential == tonumber(ARGV[1]) then redis.call('EXPIRE', KEYS[2], ARGV[4]) end
if tenant > tonumber(ARGV[2]) or credential > tonumber(ARGV[3]) then
  return 0
end
return 1
`;

export function requestCost(method: string, route: string): number {
  if (method === "GET" || method === "DELETE") return 1;
  if (route.includes("capsule-plans") || route === "/v1/capsules") return 20;
  if (route === "/v1/compressions" || route === "/v1/decompressions") return 10;
  if (route === "/v1/uploads/presign" || route === "/v1/webhooks") return 5;
  return 2;
}

export interface CostRateLimiterGateway {
  consume(
    tenantSubject: string,
    credentialId: string,
    method: string,
    route: string,
  ): Promise<void>;
  close(): Promise<void>;
}

function digest(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export class CostRateLimiter implements CostRateLimiterGateway {
  private readonly redis: Redis;

  public constructor(
    url: string,
    private readonly tenantLimit: number,
    private readonly credentialRouteLimit: number,
    redis?: Redis,
  ) {
    this.redis =
      redis ??
      new Redis(url, {
        enableAutoPipelining: true,
        maxRetriesPerRequest: 2,
        lazyConnect: true,
      });
  }

  public async consume(
    tenantSubject: string,
    credentialId: string,
    method: string,
    route: string,
  ): Promise<void> {
    if (this.redis.status === "wait") await this.redis.connect();
    const bucket = Math.floor(Date.now() / (WINDOW_SECONDS * 1_000));
    const cost = requestCost(method, route);
    const tenantKey = `smcp:ratelimit:${bucket}:tenant:${digest(tenantSubject)}`;
    const credentialKey =
      `smcp:ratelimit:${bucket}:credential:${digest(credentialId)}:` +
      digest(`${method} ${route}`);
    const allowed = await this.redis.eval(
      CONSUME_SCRIPT,
      2,
      tenantKey,
      credentialKey,
      cost,
      this.tenantLimit,
      this.credentialRouteLimit,
      COUNTER_TTL_SECONDS,
    );
    if (allowed !== 1) {
      throw new ApiProblem(
        429,
        "Tenant or credential endpoint cost budget exceeded",
        "urn:smcp:problem:rate-limit-exceeded",
      );
    }
  }

  public async close(): Promise<void> {
    if (this.redis.status !== "end") await this.redis.quit();
  }
}
