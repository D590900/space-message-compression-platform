import { describe, expect, it } from "vitest";

import {
  createApiKeySchema,
  createCapsulePlanSchema,
  createCompressionSchema,
  createWebhookEndpointSchema,
  idempotencyKeySchema,
} from "../src/index.js";

describe("shared API schemas", () => {
  it("rejects unknown API-key scopes", () => {
    expect(() =>
      createApiKeySchema.parse({
        name: "invalid",
        scopes: ["root:everything"],
        expires_at: "2030-01-01T00:00:00Z",
      }),
    ).toThrow();
  });

  it("rejects unknown compression properties", () => {
    expect(() =>
      createCompressionSchema.parse({
        project_id: "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
        source_object_id: "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce",
        input_type: "TEXT",
        profile: "faithful",
        tenant_subject: "org_attacker",
      }),
    ).toThrow();
  });

  it("requires a bounded visible idempotency key", () => {
    expect(idempotencyKeySchema.safeParse("request-0001").success).toBe(true);
    expect(idempotencyKeySchema.safeParse("short").success).toBe(false);
    expect(idempotencyKeySchema.safeParse("contains space").success).toBe(
      false,
    );
  });

  it("applies the capsule budget default and rejects duplicate jobs", () => {
    const projectId = "85bd5e09-a8fb-4d2c-a560-5d2365badf84";
    const jobId = "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce";
    const item = { job_id: jobId, required: true, utility: 10 };
    expect(
      createCapsulePlanSchema.parse({ project_id: projectId, items: [item] })
        .budget_bytes,
    ).toBe(2_000_000);
    expect(
      createCapsulePlanSchema.safeParse({
        project_id: projectId,
        items: [item, item],
      }).success,
    ).toBe(false);
  });

  it("accepts only HTTPS domain webhook endpoints and known events", () => {
    const base = {
      project_id: "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
      event_types: ["compression.completed"],
    };
    expect(
      createWebhookEndpointSchema.safeParse({
        ...base,
        url: "https://events.example.com/smcp",
      }).success,
    ).toBe(true);
    expect(
      createWebhookEndpointSchema.safeParse({
        ...base,
        url: "http://events.example.com/smcp",
      }).success,
    ).toBe(false);
  });
});
