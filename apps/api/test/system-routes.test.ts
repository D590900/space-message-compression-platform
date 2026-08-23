import { afterEach, describe, expect, it, vi } from "vitest";

import { buildApp } from "../src/app.js";
import type { ClerkGateway, ManagedApiKey } from "../src/auth.js";
import { loadConfig } from "../src/config.js";
import type { Database } from "../src/database.js";
import type { JobQueue } from "../src/queue.js";
import type { ObjectStorage } from "../src/storage.js";

const rateLimiter = {
  consume: () => Promise.resolve(),
  close: () => Promise.resolve(),
};

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
});

const managedKey: ManagedApiKey = {
  id: "apikey_test",
  name: "test",
  subject: "org_test",
  scopes: ["codecs:read", "jobs:create"],
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
  getApiKeySecret: () => Promise.resolve("test-secret"),
  revokeApiKey: () => Promise.resolve(),
};

describe("system capability routes", () => {
  const apps: Awaited<ReturnType<typeof buildApp>>["app"][] = [];
  afterEach(async () => {
    await Promise.all(apps.splice(0).map((app) => app.close()));
  });

  it("returns enabled and disabled codecs only with codecs:read", async () => {
    const createCompressionJob = vi.fn();
    const auditApiKeyUsage = vi.fn(() => Promise.resolve());
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
      createCompressionJob,
      auditApiKeyUsage,
      close: () => Promise.resolve(),
    } as unknown as Database;
    const queue = { close: () => Promise.resolve() } as unknown as JobQueue;
    const storage = {} as ObjectStorage;
    const { app } = await buildApp(config, {
      database,
      queue,
      storage,
      clerk,
      rateLimiter,
    });
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

    const rejected = await app.inject({ method: "GET", url: "/v1/models" });
    expect(rejected.statusCode).toBe(401);

    const metrics = await app.inject({ method: "GET", url: "/metrics" });
    expect(metrics.statusCode).toBe(200);
    expect(metrics.headers["content-type"]).toContain("text/plain");
    expect(metrics.body).toContain("smcp_api_http_requests_total");
    expect(metrics.body).toContain(
      'api_key_verification_failures_total{reason="unauthorized"} 1',
    );

    const semantic = await app.inject({
      method: "POST",
      url: "/v1/compressions",
      headers: {
        authorization: "Bearer test-key",
        "idempotency-key": "semantic-profile-0001",
      },
      payload: {
        project_id: "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
        source_object_id: "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce",
        input_type: "TEXT",
        profile: "semantic",
      },
    });
    expect(semantic.statusCode).toBe(422);
    expect(semantic.json()).toMatchObject({
      type: "urn:smcp:problem:semantic-profile-unavailable",
    });
    expect(createCompressionJob).not.toHaveBeenCalled();
    expect(auditApiKeyUsage).toHaveBeenCalledTimes(2);
    expect(auditApiKeyUsage).toHaveBeenLastCalledWith(
      "org_test",
      "user_test",
      "apikey_test",
      expect.any(String),
      "POST",
      "/v1/compressions",
      "success",
    );
  });

  it("accepts semantic jobs only when the runtime registry exposes the profile", async () => {
    const createCompressionJob = vi.fn(() =>
      Promise.resolve({
        created: true,
        job: { id: "semantic-job", status: "PENDING" },
      }),
    );
    const database = {
      listCodecCapabilities: () =>
        Promise.resolve([
          {
            id: "image.cod-lite",
            version: "bpp-0.0312-hf-cfda8135320f",
            content_type: "IMAGE",
            implementation_sha256: "ab".repeat(32),
            deterministic: false,
            enabled: true,
            disabled_reason: null,
            capability: { profiles: ["ultra", "semantic"] },
          },
        ]),
      createCompressionJob,
      auditApiKeyUsage: () => Promise.resolve(),
      close: () => Promise.resolve(),
    } as unknown as Database;
    const { app } = await buildApp(config, {
      database,
      queue: { close: () => Promise.resolve() } as unknown as JobQueue,
      storage: {} as ObjectStorage,
      clerk,
      rateLimiter,
    });
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: "/v1/compressions",
      headers: {
        authorization: "Bearer test-key",
        "idempotency-key": "semantic-profile-enabled-0001",
      },
      payload: {
        project_id: "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
        source_object_id: "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce",
        input_type: "IMAGE",
        profile: "semantic",
      },
    });

    expect(response.statusCode).toBe(202);
    expect(createCompressionJob).toHaveBeenCalledOnce();
  });

  it("accepts an authenticated organization session without exposing an API key", async () => {
    const verifyApiKey = vi.fn();
    const authenticateSession = vi.fn(() =>
      Promise.resolve({
        kind: "session" as const,
        tenantSubject: "org_dashboard",
        actorSubject: "user_dashboard",
        organizationRole: "org:admin",
      }),
    );
    const sessionClerk = {
      ...clerk,
      verifyApiKey,
      authenticateSession,
    };
    const listCodecCapabilities = vi.fn(() => Promise.resolve([]));
    const createCompressionJob = vi.fn(() =>
      Promise.resolve({
        created: false,
        job: { id: "job_session", status: "PENDING" },
      }),
    );
    const auditApiKeyUsage = vi.fn(() => Promise.resolve());
    const database = {
      listCodecCapabilities,
      createCompressionJob,
      auditApiKeyUsage,
      close: () => Promise.resolve(),
    } as unknown as Database;
    const consume = vi.fn(() => Promise.resolve());
    const { app } = await buildApp(config, {
      database,
      queue: {
        close: () => Promise.resolve(),
      } as unknown as JobQueue,
      storage: {} as ObjectStorage,
      clerk: sessionClerk,
      rateLimiter: {
        consume,
        close: () => Promise.resolve(),
      },
    });
    apps.push(app);

    const response = await app.inject({
      method: "GET",
      url: "/v1/codecs",
      headers: { authorization: "Bearer clerk-session-token" },
    });

    expect(response.statusCode).toBe(200);
    expect(listCodecCapabilities).toHaveBeenCalledOnce();
    expect(authenticateSession).toHaveBeenCalledOnce();
    expect(verifyApiKey).not.toHaveBeenCalled();
    expect(auditApiKeyUsage).not.toHaveBeenCalled();
    expect(consume).toHaveBeenCalledWith(
      "org_dashboard",
      "session:user_dashboard",
      "GET",
      "/v1/codecs",
    );

    const compression = await app.inject({
      method: "POST",
      url: "/v1/compressions",
      headers: {
        authorization: "Bearer clerk-session-token",
        "idempotency-key": "session-job-0001",
      },
      payload: {
        project_id: "85bd5e09-a8fb-4d2c-a560-5d2365badf84",
        source_object_id: "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce",
        input_type: "TEXT",
        profile: "faithful",
      },
    });
    expect(compression.statusCode).toBe(202);
    expect(createCompressionJob).toHaveBeenCalledWith(
      "org_dashboard",
      "user_dashboard",
      null,
      expect.any(String),
      "session-job-0001",
      expect.objectContaining({ input_type: "TEXT" }),
    );
  });

  it("forwards cancellation idempotency keys to the atomic database mutation", async () => {
    const jobId = "2d0610bd-4567-41ab-9a7a-8a5fd320c7ce";
    const cancelCompressionJob = vi.fn(() =>
      Promise.resolve({ id: jobId, status: "CANCELLED" }),
    );
    const cancellationClerk = {
      ...clerk,
      verifyApiKey: () =>
        Promise.resolve({ ...managedKey, scopes: ["jobs:cancel"] }),
    };
    const database = {
      cancelCompressionJob,
      auditApiKeyUsage: () => Promise.resolve(),
      close: () => Promise.resolve(),
    } as unknown as Database;
    const { app } = await buildApp(config, {
      database,
      queue: { close: () => Promise.resolve() } as unknown as JobQueue,
      storage: {} as ObjectStorage,
      clerk: cancellationClerk,
      rateLimiter,
    });
    apps.push(app);

    const response = await app.inject({
      method: "POST",
      url: `/v1/compressions/${jobId}/cancel`,
      headers: {
        authorization: "Bearer test-key",
        "idempotency-key": "cancel-job-0001",
      },
    });

    expect(response.statusCode).toBe(202);
    expect(cancelCompressionJob).toHaveBeenCalledWith(
      "org_test",
      "user_test",
      "apikey_test",
      expect.any(String),
      "cancel-job-0001",
      jobId,
    );
  });

  it("lists dashboard resources through bounded tenant-scoped pages", async () => {
    const projectId = "85bd5e09-a8fb-4d2c-a560-5d2365badf84";
    const sessionClerk = {
      ...clerk,
      authenticateSession: () =>
        Promise.resolve({
          kind: "session" as const,
          tenantSubject: "org_dashboard",
          actorSubject: "user_dashboard",
          organizationRole: "org:admin",
        }),
    };
    const listProjects = vi.fn(() =>
      Promise.resolve({ totalCount: 0, data: [] }),
    );
    const listCompressionJobs = vi.fn(() =>
      Promise.resolve({ totalCount: 0, data: [] }),
    );
    const listArtifacts = vi.fn(() =>
      Promise.resolve({ totalCount: 0, data: [] }),
    );
    const listCapsules = vi.fn(() =>
      Promise.resolve({ totalCount: 0, data: [] }),
    );
    const updateProjectSettings = vi.fn(() =>
      Promise.resolve({
        id: projectId,
        tenant_subject: "org_dashboard",
        name: "Mission telemetry",
        quality_policy: { image: { ms_ssim_min: 0.96 } },
        original_retention_seconds: 86_400,
        created_at: new Date(),
      }),
    );
    const database = {
      listProjects,
      listCompressionJobs,
      listArtifacts,
      listCapsules,
      updateProjectSettings,
      close: () => Promise.resolve(),
    } as unknown as Database;
    const { app } = await buildApp(config, {
      database,
      queue: { close: () => Promise.resolve() } as unknown as JobQueue,
      storage: {} as ObjectStorage,
      clerk: sessionClerk,
      rateLimiter,
    });
    apps.push(app);
    const headers = { authorization: "Bearer clerk-session-token" };

    const projects = await app.inject({
      method: "GET",
      url: "/v1/projects?limit=25&offset=5",
      headers,
    });
    const jobs = await app.inject({
      method: "GET",
      url: `/v1/compressions?project_id=${projectId}&limit=20`,
      headers,
    });
    const artifacts = await app.inject({
      method: "GET",
      url: `/v1/artifacts?project_id=${projectId}`,
      headers,
    });
    const capsules = await app.inject({
      method: "GET",
      url: `/v1/capsules?project_id=${projectId}&offset=2`,
      headers,
    });
    const settings = await app.inject({
      method: "PATCH",
      url: `/v1/projects/${projectId}/settings`,
      headers: { ...headers, "content-type": "application/json" },
      payload: {
        quality_policy: { image: { ms_ssim_min: 0.96 } },
        original_retention_seconds: 86_400,
      },
    });

    expect([
      projects.statusCode,
      jobs.statusCode,
      artifacts.statusCode,
      capsules.statusCode,
      settings.statusCode,
    ]).toEqual([200, 200, 200, 200, 200]);
    expect(projects.json()).toMatchObject({
      total_count: 0,
      limit: 25,
      offset: 5,
    });
    expect(listProjects).toHaveBeenCalledWith("org_dashboard", 25, 5);
    expect(listCompressionJobs).toHaveBeenCalledWith(
      "org_dashboard",
      projectId,
      20,
      0,
    );
    expect(listArtifacts).toHaveBeenCalledWith(
      "org_dashboard",
      projectId,
      50,
      0,
    );
    expect(listCapsules).toHaveBeenCalledWith(
      "org_dashboard",
      projectId,
      50,
      2,
    );
    expect(updateProjectSettings).toHaveBeenCalledWith(
      "org_dashboard",
      "user_dashboard",
      expect.any(String),
      projectId,
      {
        quality_policy: { image: { ms_ssim_min: 0.96 } },
        original_retention_seconds: 86_400,
      },
    );

    const rejected = await app.inject({
      method: "GET",
      url: `/v1/compressions?project_id=${projectId}&limit=101`,
      headers,
    });
    expect(rejected.statusCode).toBe(400);
    expect(listCompressionJobs).toHaveBeenCalledOnce();
  });
});
