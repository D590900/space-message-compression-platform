import { afterEach, describe, expect, it, vi } from "vitest";

import { buildApp } from "../src/app.js";
import type { ClerkGateway, ManagedApiKey } from "../src/auth.js";
import type { CapsulePlannerGateway } from "../src/capsule-planner.js";
import { loadConfig } from "../src/config.js";
import type { Database } from "../src/database.js";
import type { JobQueue } from "../src/queue.js";
import type { ObjectStorage } from "../src/storage.js";

const projectId = "85bd5e09-a8fb-4d2c-a560-5d2365badf84";
const jobId = "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce";
const candidateId = "aa094429-9960-46fb-990a-4f5ca416a3b2";
const artifactId = "88f8f12f-93b8-4d26-aa75-53e126b3693a";
const capsuleId = "7a000000-0000-4000-8000-000000000007";

const config = loadConfig({
  NODE_ENV: "test",
  LOG_LEVEL: "silent",
  DATABASE_URL: "postgresql://test:test@localhost:5432/test",
  VALKEY_URL: "redis://localhost:6379/0",
  IDENTIFIER_HMAC_SECRET: "test-identifier-hmac-secret-32-bytes",
  CLERK_SECRET_KEY: "test-secret",
  CLERK_PUBLISHABLE_KEY: "test-publishable",
  WEBHOOK_SECRET_ENCRYPTION_KEY: "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=",
  WEB_ORIGIN: "http://localhost:3000",
  API_ORIGIN: "http://localhost:3001",
  S3_ENDPOINT: "http://localhost:9000",
  S3_REGION: "us-east-1",
  S3_BUCKET: "test-bucket",
  S3_ACCESS_KEY_ID: "test",
  S3_SECRET_ACCESS_KEY: "test",
  S3_FORCE_PATH_STYLE: "true",
  CAPSULE_CLI_PATH: "unused-in-test",
});

const key: ManagedApiKey = {
  id: "apikey_test",
  name: "test",
  subject: "org_test",
  scopes: ["capsules:plan", "capsules:read"],
  claims: { smcp_issued: true },
  createdBy: "user_test",
  description: null,
  expiration: Date.now() + 60_000,
  expired: false,
  revoked: false,
};

const clerk: ClerkGateway = {
  verifyApiKey: () => Promise.resolve(key),
  authenticateSession: () => Promise.resolve(null),
  createApiKey: () => Promise.resolve(key),
  listApiKeys: () => Promise.resolve({ data: [key], totalCount: 1 }),
  getApiKey: () => Promise.resolve(key),
  getApiKeySecret: () => Promise.resolve("test-secret"),
  revokeApiKey: () => Promise.resolve(),
};

const rateLimiter = {
  consume: () => Promise.resolve(),
  close: () => Promise.resolve(),
};

describe("capsule planning", () => {
  const apps: Awaited<ReturnType<typeof buildApp>>["app"][] = [];
  afterEach(async () => {
    await Promise.all(apps.splice(0).map((app) => app.close()));
  });

  it("passes actual candidate sizes to the Rust planner and persists its explanation", async () => {
    const createCapsulePlan = vi.fn(
      (_tenant, _actor, _key, _request, _idempotency, input, solver, report) =>
        Promise.resolve({
          created: true,
          plan: {
            id: "3c7bd1db-bfb7-4477-b865-4c28b2cf1054",
            tenant_subject: "org_test",
            project_id: projectId,
            budget_bytes: input.budget_bytes,
            ecc_percent: input.ecc_percent,
            status: "COMPLETED",
            solver,
            report,
            created_at: new Date("2026-08-22T00:00:00Z"),
          },
        }),
    );
    const database = {
      auditApiKeyUsage: () => Promise.resolve(),
      getCapsuleCandidates: () =>
        Promise.resolve([
          {
            job_id: jobId,
            input_type: "TEXT",
            candidate_id: candidateId,
            artifact_id: artifactId,
            codec_id: "text.zstandard",
            codec_version: "0.25.0",
            payload_bytes: 500,
            container_overhead_bytes: 0,
          },
        ]),
      createCapsulePlan,
      close: () => Promise.resolve(),
    } as unknown as Database;
    const planner = {
      plan: vi.fn(() =>
        Promise.resolve({
          solver: "exact" as const,
          actual_bytes: 1000,
          total_utility: 10,
          included_items: 1,
          selections: [
            {
              item_id: jobId,
              candidate_id: candidateId,
              bytes: 510,
              utility: 10,
              reason: "global optimum",
            },
          ],
        }),
      ),
    } satisfies CapsulePlannerGateway;
    const { app } = await buildApp(config, {
      database,
      queue: { close: () => Promise.resolve() } as unknown as JobQueue,
      storage: {} as unknown as ObjectStorage,
      clerk,
      capsulePlanner: planner,
      rateLimiter,
    });
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: "/v1/capsule-plans",
      headers: {
        authorization: "Bearer test-key",
        "idempotency-key": "capsule-plan-0001",
      },
      payload: {
        project_id: projectId,
        items: [{ job_id: jobId, required: true, utility: 10 }],
      },
    });

    expect(response.statusCode).toBe(201);
    expect(planner.plan).toHaveBeenCalledWith(
      expect.objectContaining({
        budget_bytes: 2_000_000,
        items: [
          expect.objectContaining({
            candidates: [
              expect.objectContaining({ id: candidateId, bytes: 510 }),
            ],
          }),
        ],
      }),
    );
    expect(createCapsulePlan).toHaveBeenCalledWith(
      "org_test",
      "user_test",
      "apikey_test",
      expect.any(String),
      "capsule-plan-0001",
      expect.any(Object),
      "exact",
      expect.objectContaining({
        selections: [expect.objectContaining({ artifact_id: artifactId })],
      }),
    );
  });

  it("returns the persisted Rust build verification attestation", async () => {
    const database = {
      auditApiKeyUsage: () => Promise.resolve(),
      getCapsule: () =>
        Promise.resolve({
          id: capsuleId,
          tenant_subject: "org_test",
          project_id: projectId,
          plan_id: "60000000-0000-0000-0000-000000000006",
          budget_bytes: 2_000_000,
          actual_bytes: 649,
          object_key: "org_test/project/capsules/test.smcp",
          sha256_hex: "ab".repeat(32),
          merkle_root_hex: "cd".repeat(32),
          format_major: 1,
          format_minor: 0,
          status: "COMPLETED",
          error_code: null,
          build_options: {},
          created_at: new Date("2026-08-22T00:00:00Z"),
          completed_at: new Date("2026-08-22T00:00:01Z"),
        }),
      close: () => Promise.resolve(),
    } as unknown as Database;
    const { app } = await buildApp(config, {
      database,
      queue: { close: () => Promise.resolve() } as unknown as JobQueue,
      storage: {} as unknown as ObjectStorage,
      clerk,
      rateLimiter,
    });
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: "/v1/capsules/verify",
      headers: { authorization: "Bearer test-key" },
      payload: { project_id: projectId, capsule_id: capsuleId },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({
      valid: true,
      actual_bytes: 649,
      within_budget: true,
      verification_source: "build-time-rust-verifier",
    });
  });
});
