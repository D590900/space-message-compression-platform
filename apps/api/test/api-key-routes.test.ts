import { afterEach, describe, expect, it, vi } from "vitest";

import { buildApp } from "../src/app.js";
import type { ClerkGateway, ManagedApiKey } from "../src/auth.js";
import { loadConfig } from "../src/config.js";
import type { Database } from "../src/database.js";
import type { KeyRotationSchedulerGateway } from "../src/key-rotation-scheduler.js";
import type { JobQueue } from "../src/queue.js";
import type { ObjectStorage } from "../src/storage.js";
import type { WebhookDispatcherGateway } from "../src/webhook-dispatcher.js";

const config = loadConfig({
  NODE_ENV: "test",
  LOG_LEVEL: "silent",
  DATABASE_URL: "postgresql://test:test@localhost:5432/test",
  VALKEY_URL: "redis://localhost:6379/0",
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
});

function key(overrides: Partial<ManagedApiKey> = {}): ManagedApiKey {
  return {
    id: "apikey_created",
    name: "automation",
    subject: "org_test",
    scopes: ["jobs:create"],
    claims: { smcp_issued: true },
    createdBy: "user_test",
    description: null,
    expiration: Date.now() + 3_600_000,
    expired: false,
    revoked: false,
    secret: "smcp-secret",
    ...overrides,
  };
}

function dependencies(database: Database, clerk: ClerkGateway) {
  const queue = { close: () => Promise.resolve() } as unknown as JobQueue;
  const storage = {} as ObjectStorage;
  const keyRotationScheduler: KeyRotationSchedulerGateway = {
    start: () => undefined,
    close: () => Promise.resolve(),
  };
  const webhookDispatcher: WebhookDispatcherGateway = {
    start: () => undefined,
    close: () => Promise.resolve(),
  };
  return {
    database,
    clerk,
    queue,
    storage,
    keyRotationScheduler,
    webhookDispatcher,
  };
}

describe("API-key lifecycle routes", () => {
  const apps: Awaited<ReturnType<typeof buildApp>>["app"][] = [];
  afterEach(async () => {
    await Promise.all(apps.splice(0).map((app) => app.close()));
  });

  it("creates once with an operation marker and completes the durable claim", async () => {
    const complete = vi.fn(() => Promise.resolve());
    const database = {
      claimExternalMutation: () =>
        Promise.resolve({ state: "claimed", operationId: "operation-1" }),
      completeExternalApiKeyCreation: complete,
      close: () => Promise.resolve(),
    } as unknown as Database;
    const create = vi.fn((input) =>
      Promise.resolve(key({ claims: input.claims as Record<string, unknown> })),
    );
    const clerk = {
      authenticateSession: () =>
        Promise.resolve({
          kind: "session" as const,
          tenantSubject: "org_test",
          actorSubject: "user_test",
        }),
      listApiKeys: () => Promise.resolve({ data: [], totalCount: 0 }),
      createApiKey: create,
      getApiKeySecret: () => Promise.resolve("smcp-secret"),
    } as unknown as ClerkGateway;
    const { app } = await buildApp(config, dependencies(database, clerk));
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: "/v1/api-keys",
      headers: { "idempotency-key": "stable-create-key" },
      payload: {
        name: "automation",
        scopes: ["jobs:create", "jobs:create"],
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      },
    });

    expect(response.statusCode).toBe(201);
    expect(response.json()).toMatchObject({
      id: "apikey_created",
      secret: "smcp-secret",
    });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        scopes: ["jobs:create"],
        claims: {
          smcp_issued: true,
          smcp_operation_id: "operation-1",
        },
      }),
    );
    expect(complete).toHaveBeenCalledOnce();
  });

  it("does not duplicate or redisplay a completed one-time secret", async () => {
    const stored = key({ secret: undefined });
    const database = {
      claimExternalMutation: () =>
        Promise.resolve({
          state: "completed",
          operationId: "operation-1",
          externalResourceId: stored.id,
          responseStatus: 201,
          responseBody: stored,
        }),
      close: () => Promise.resolve(),
    } as unknown as Database;
    const create = vi.fn();
    const clerk = {
      authenticateSession: () =>
        Promise.resolve({
          kind: "session" as const,
          tenantSubject: "org_test",
          actorSubject: "user_test",
        }),
      createApiKey: create,
      getApiKeySecret: () => Promise.resolve("same-secret"),
    } as unknown as ClerkGateway;
    const { app } = await buildApp(config, dependencies(database, clerk));
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: "/v1/api-keys",
      headers: { "idempotency-key": "stable-create-key" },
      payload: {
        name: "automation",
        scopes: ["jobs:create"],
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      },
    });

    expect(response.statusCode).toBe(409);
    expect(response.json()).toMatchObject({
      type: "urn:smcp:problem:one-time-secret-already-issued",
    });
    expect(create).not.toHaveBeenCalled();
  });

  it("reconciles a crash-created Clerk key by its operation claim", async () => {
    const recovered = key({
      secret: undefined,
      claims: { smcp_issued: true, smcp_operation_id: "operation-1" },
    });
    const complete = vi.fn(() => Promise.resolve());
    const database = {
      claimExternalMutation: () =>
        Promise.resolve({ state: "claimed", operationId: "operation-1" }),
      completeExternalApiKeyCreation: complete,
      close: () => Promise.resolve(),
    } as unknown as Database;
    const create = vi.fn();
    const clerk = {
      authenticateSession: () =>
        Promise.resolve({
          kind: "session" as const,
          tenantSubject: "org_test",
          actorSubject: "user_test",
        }),
      listApiKeys: () => Promise.resolve({ data: [recovered], totalCount: 1 }),
      createApiKey: create,
      getApiKeySecret: () => Promise.resolve("recovered-secret"),
    } as unknown as ClerkGateway;
    const { app } = await buildApp(config, dependencies(database, clerk));
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: "/v1/api-keys",
      headers: { "idempotency-key": "stable-create-key" },
      payload: {
        name: "automation",
        scopes: ["jobs:create"],
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      },
    });

    expect(response.statusCode).toBe(201);
    expect(response.json()).toMatchObject({ secret: "recovered-secret" });
    expect(create).not.toHaveBeenCalled();
    expect(complete).toHaveBeenCalledOnce();
  });
});
