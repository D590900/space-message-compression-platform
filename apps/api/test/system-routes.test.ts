import { afterEach, describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";
import type { ClerkGateway, ManagedApiKey } from "../src/auth.js";
import { loadConfig } from "../src/config.js";
import type { Database } from "../src/database.js";
import type { JobQueue } from "../src/queue.js";
import type { ObjectStorage } from "../src/storage.js";

const config = loadConfig({
  NODE_ENV: "test",
  LOG_LEVEL: "silent",
  DATABASE_URL: "postgresql://test:test@localhost:5432/test",
  VALKEY_URL: "redis://localhost:6379/0",
  CLERK_SECRET_KEY: "test-secret",
  CLERK_PUBLISHABLE_KEY: "test-publishable",
  WEB_ORIGIN: "http://localhost:3000",
  API_ORIGIN: "http://localhost:3001",
  S3_ENDPOINT: "http://localhost:9000",
  S3_REGION: "us-east-1",
  S3_BUCKET: "test-bucket",
  S3_ACCESS_KEY_ID: "test",
  S3_SECRET_ACCESS_KEY: "test",
  S3_FORCE_PATH_STYLE: "true",
});

const managedKey: ManagedApiKey = {
  id: "apikey_test",
  name: "test",
  subject: "org_test",
  scopes: ["codecs:read"],
  claims: { smcp_issued: true },
  createdBy: "user_test",
  description: null,
  expiration: Date.now() + 60_000,
  expired: false,
  revoked: false,
};

const clerk: ClerkGateway = {
  verifyApiKey: () => Promise.resolve(managedKey),
  authenticateSession: () => Promise.resolve(null),
  createApiKey: () => Promise.resolve(managedKey),
  listApiKeys: () => Promise.resolve({ data: [managedKey], totalCount: 1 }),
  getApiKey: () => Promise.resolve(managedKey),
  revokeApiKey: () => Promise.resolve(),
};

describe("system capability routes", () => {
  const apps: Awaited<ReturnType<typeof buildApp>>["app"][] = [];
  afterEach(async () => {
    await Promise.all(apps.splice(0).map((app) => app.close()));
  });

  it("returns enabled and disabled codecs only with codecs:read", async () => {
    const database = {
      listCodecCapabilities: () =>
        Promise.resolve([
          {
            id: "image.avif",
            version: "1.4.2",
            content_type: "IMAGE",
            implementation_sha256: "ab".repeat(32),
            deterministic: true,
            enabled: true,
            disabled_reason: null,
            capability: { profiles: ["faithful", "ultra"] },
          },
          {
            id: "image.compressai",
            version: "unavailable",
            content_type: "IMAGE",
            implementation_sha256: "cd".repeat(32),
            deterministic: false,
            enabled: false,
            disabled_reason: "no verified weights",
            capability: { install_hint: "install from an immutable manifest" },
          },
        ]),
      close: () => Promise.resolve(),
    } as unknown as Database;
    const queue = { close: () => Promise.resolve() } as unknown as JobQueue;
    const storage = {} as ObjectStorage;
    const { app } = await buildApp(config, { database, queue, storage, clerk });
    apps.push(app);

    const response = await app.inject({
      method: "GET",
      url: "/v1/codecs",
      headers: { authorization: "Bearer test-key" },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({
      total_count: 2,
      data: [
        { id: "image.avif", enabled: true },
        {
          id: "image.compressai",
          enabled: false,
          disabled_reason: "no verified weights",
        },
      ],
    });
  });
});
