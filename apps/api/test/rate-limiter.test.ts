import type { Redis } from "ioredis";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../src/problem.js";
import { CostRateLimiter, requestCost } from "../src/rate-limiter.js";

describe("request cost classification", () => {
  it.each([
    ["GET", "/v1/compressions/123", 1],
    ["DELETE", "/v1/api-keys/123", 1],
    ["POST", "/v1/capsule-plans", 20],
    ["POST", "/v1/capsules", 20],
    ["POST", "/v1/compressions", 10],
    ["POST", "/v1/decompressions", 10],
    ["POST", "/v1/uploads/presign", 5],
    ["POST", "/v1/webhooks", 5],
    ["POST", "/v1/projects", 2],
  ])("charges %s %s a cost of %i", (method, route, expected) => {
    expect(requestCost(method, route)).toBe(expected);
  });
});

describe("CostRateLimiter", () => {
  it("uses hashed tenant and credential-route keys for one atomic decision", async () => {
    const evalScript = vi.fn(() => Promise.resolve(1));
    const redis = {
      status: "ready",
      eval: evalScript,
      quit: () => Promise.resolve("OK"),
    } as unknown as Redis;
    const limiter = new CostRateLimiter(
      "redis://unused",
      1_000,
      120,
      "test-identifier-hmac-secret-32-bytes",
      redis,
    );

    await limiter.consume(
      "org_private",
      "apikey_private",
      "POST",
      "/v1/compressions",
    );

    expect(evalScript).toHaveBeenCalledOnce();
    const call = evalScript.mock.calls[0];
    expect(call?.[1]).toBe(2);
    expect(call?.[2]).not.toContain("org_private");
    expect(call?.[3]).not.toContain("apikey_private");
    expect(call?.slice(4)).toEqual([10, 1_000, 120, 120]);
  });

  it("returns a stable 429 problem when either budget is exhausted", async () => {
    const redis = {
      status: "ready",
      eval: () => Promise.resolve(0),
      quit: () => Promise.resolve("OK"),
    } as unknown as Redis;
    const limiter = new CostRateLimiter(
      "redis://unused",
      1_000,
      120,
      "test-identifier-hmac-secret-32-bytes",
      redis,
    );

    await expect(
      limiter.consume("org", "key", "POST", "/v1/capsules"),
    ).rejects.toMatchObject<ApiProblem>({
      status: 429,
      type: "urn:smcp:problem:rate-limit-exceeded",
    });
  });
});
