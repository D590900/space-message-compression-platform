import { createHmac, randomBytes, randomUUID } from "node:crypto";

import rateLimit from "@fastify/rate-limit";
import {
  apiKeyIdParamsSchema,
  createApiKeySchema,
  createCapsulePlanSchema,
  createCapsuleSchema,
  createCompressionSchema,
  createDecompressionSchema,
  createProjectSchema,
  createWebhookEndpointSchema,
  idempotencyKeySchema,
  paginationQuerySchema,
  presignUploadSchema,
  projectCollectionQuerySchema,
  projectIdQuerySchema,
  resourceIdParamsSchema,
  rotateApiKeySchema,
  updateProjectSettingsSchema,
  verifyCapsuleSchema,
  type ApiScope,
} from "@smcp/schemas";
import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";

import {
  ApiKeyPolicyProblem,
  type ClerkGateway,
  ProductionClerkGateway,
  requireApiKey,
  requireOrganizationAdmin,
  requireSession,
} from "./auth.js";
import type { ApiConfig } from "./config.js";
import {
  type CapsulePlannerGateway,
  RustCapsulePlanner,
} from "./capsule-planner.js";
import { Database } from "./database.js";
import { toWebRequest } from "./http-request.js";
import {
  JobOutboxPublisher,
  type JobOutboxPublisherGateway,
} from "./job-outbox-publisher.js";
import {
  KeyRotationScheduler,
  type KeyRotationSchedulerGateway,
} from "./key-rotation-scheduler.js";
import { ApiProblem, registerProblemHandler } from "./problem.js";
import { ApiMetrics, authorizeMetrics } from "./metrics.js";
import { JobQueue } from "./queue.js";
import {
  CostRateLimiter,
  type CostRateLimiterGateway,
} from "./rate-limiter.js";
import { SecretBox } from "./secret-box.js";
import { ObjectStorage } from "./storage.js";
import {
  WebhookDispatcher,
  type WebhookDispatcherGateway,
} from "./webhook-dispatcher.js";
import { resolvePublicWebhookUrl } from "./webhook-url.js";

export type AppDependencies = {
  database: Database;
  queue: JobQueue;
  storage: ObjectStorage;
  clerk: ClerkGateway;
  capsulePlanner: CapsulePlannerGateway;
  keyRotationScheduler: KeyRotationSchedulerGateway;
  webhookDispatcher: WebhookDispatcherGateway;
  metrics: ApiMetrics;
  rateLimiter: CostRateLimiterGateway;
  jobOutboxPublisher: JobOutboxPublisherGateway;
};

function idempotencyKey(request: FastifyRequest): string {
  return idempotencyKeySchema.parse(request.headers["idempotency-key"]);
}

function safeKeySegment(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 120);
}

export async function buildApp(
  config: ApiConfig,
  overrides: Partial<AppDependencies> = {},
): Promise<{ app: FastifyInstance; dependencies: AppDependencies }> {
  const database =
    overrides.database ??
    new Database(config.DATABASE_URL, config.IDENTIFIER_HMAC_SECRET);
  const clerk = overrides.clerk ?? new ProductionClerkGateway(config);
  const queue = overrides.queue ?? new JobQueue(config.VALKEY_URL);
  const webhookSecretBox = new SecretBox(config.WEBHOOK_SECRET_ENCRYPTION_KEY);
  const dependencies: AppDependencies = {
    database,
    queue,
    storage: overrides.storage ?? new ObjectStorage(config),
    clerk,
    capsulePlanner:
      overrides.capsulePlanner ??
      new RustCapsulePlanner(config.CAPSULE_CLI_PATH),
    keyRotationScheduler:
      overrides.keyRotationScheduler ??
      new KeyRotationScheduler(database, clerk, config.KEY_ROTATION_POLL_MS),
    webhookDispatcher:
      overrides.webhookDispatcher ??
      new WebhookDispatcher(
        database,
        config.WEBHOOK_SECRET_ENCRYPTION_KEY,
        config.WEBHOOK_POLL_MS,
        config.WEBHOOK_MAX_ATTEMPTS,
        config.WEBHOOK_TIMEOUT_MS,
      ),
    metrics: overrides.metrics ?? new ApiMetrics(),
    rateLimiter:
      overrides.rateLimiter ??
      new CostRateLimiter(
        config.VALKEY_URL,
        config.TENANT_RATE_COST_PER_MINUTE,
        config.CREDENTIAL_ROUTE_COST_PER_MINUTE,
        config.IDENTIFIER_HMAC_SECRET,
      ),
    jobOutboxPublisher:
      overrides.jobOutboxPublisher ??
      new JobOutboxPublisher(database, queue, config.JOB_OUTBOX_POLL_MS),
  };
  dependencies.keyRotationScheduler.start();
  dependencies.webhookDispatcher.start();
  dependencies.jobOutboxPublisher.start();

  const app = Fastify({
    logger: {
      level: config.LOG_LEVEL,
      redact: ["req.headers.authorization", "req.headers.cookie"],
    },
    bodyLimit: 1_048_576,
    genReqId: () => randomUUID(),
    requestIdHeader: "x-request-id",
  });

  await app.register(rateLimit, {
    max: 120,
    timeWindow: "1 minute",
    keyGenerator: (request) => {
      const credential =
        request.headers.authorization ?? request.headers.cookie ?? request.ip;
      const route = request.routeOptions.url ?? request.url.split("?")[0];
      const credentialDigest = createHmac(
        "sha256",
        config.IDENTIFIER_HMAC_SECRET,
      )
        .update("pre-auth\0")
        .update(credential)
        .digest("hex");
      return `${request.method}:${route}:${credentialDigest}`;
    },
  });

  const requestStarts = new WeakMap<FastifyRequest, bigint>();
  app.addHook("onRequest", async (request) => {
    requestStarts.set(request, process.hrtime.bigint());
  });
  app.addHook("onResponse", async (request, reply) => {
    dependencies.metrics.observeRequest(
      request,
      reply.statusCode,
      requestStarts.get(request) ?? process.hrtime.bigint(),
    );
  });

  app.setErrorHandler((error, request, reply) =>
    registerProblemHandler(request, reply, error),
  );

  app.get("/health/live", async () => ({ status: "ok" }));
  app.get("/health/ready", async (_request, reply) => {
    try {
      await Promise.all([
        dependencies.database.ready(),
        dependencies.queue.ready(),
      ]);
      return { status: "ready" };
    } catch {
      return reply.status(503).send({ status: "not_ready" });
    }
  });

  app.get("/metrics", async (request, reply) => {
    if (!authorizeMetrics(request, config)) {
      throw new ApiProblem(
        401,
        "Metrics authentication required",
        "urn:smcp:problem:unauthorized",
      );
    }
    return reply
      .type(dependencies.metrics.registry.contentType)
      .send(await dependencies.metrics.registry.metrics());
  });

  const apiPrincipal = async (request: FastifyRequest, scope: ApiScope) => {
    const route =
      request.routeOptions.url ?? request.url.split("?")[0] ?? request.url;
    let principal;
    try {
      principal = await requireApiKey(
        dependencies.clerk,
        request.headers.authorization,
        scope,
      );
    } catch (error) {
      if (error instanceof ApiKeyPolicyProblem) {
        await dependencies.database.auditApiKeyUsage(
          error.principal.tenantSubject,
          error.principal.actorSubject,
          error.principal.keyId,
          request.id,
          request.method,
          route,
          "error",
          error.type,
        );
      }
      dependencies.metrics.recordApiKeyFailure(
        error instanceof ApiProblem ? error.type : "unknown",
      );
      throw error;
    }
    try {
      await dependencies.rateLimiter.consume(
        principal.tenantSubject,
        principal.keyId,
        request.method,
        route,
      );
    } catch (error) {
      await dependencies.database.auditApiKeyUsage(
        principal.tenantSubject,
        principal.actorSubject,
        principal.keyId,
        request.id,
        request.method,
        route,
        "error",
        error instanceof ApiProblem ? error.type : "unknown",
      );
      throw error;
    }
    await dependencies.database.auditApiKeyUsage(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      request.method,
      route,
      "success",
    );
    return principal;
  };

  const sessionPrincipal = async (request: FastifyRequest) => {
    const session = await requireSession(
      dependencies.clerk,
      toWebRequest(request, config.API_ORIGIN),
    );
    await dependencies.rateLimiter.consume(
      session.tenantSubject,
      `session:${session.actorSubject}`,
      request.method,
      request.routeOptions.url ?? request.url,
    );
    return session;
  };

  const authorizedPrincipal = async (
    request: FastifyRequest,
    scope: ApiScope,
  ) => {
    const session = await dependencies.clerk.authenticateSession(
      toWebRequest(request, config.API_ORIGIN),
    );
    if (session) {
      if (scope === "webhooks:manage" || scope.startsWith("admin:")) {
        requireOrganizationAdmin(session);
      }
      await dependencies.rateLimiter.consume(
        session.tenantSubject,
        `session:${session.actorSubject}`,
        request.method,
        request.routeOptions.url ?? request.url,
      );
      return { ...session, keyId: null };
    }
    return apiPrincipal(request, scope);
  };

  app.get("/v1/codecs", async (request) => {
    await authorizedPrincipal(request, "codecs:read");
    const data = await dependencies.database.listCodecCapabilities();
    return { total_count: data.length, data };
  });

  app.get("/v1/models", async (request) => {
    await authorizedPrincipal(request, "codecs:read");
    const data = await dependencies.database.listModelManifests();
    return { total_count: data.length, data };
  });

  app.post("/v1/capsule-plans", async (request, reply) => {
    const principal = await authorizedPrincipal(request, "capsules:plan");
    const input = createCapsulePlanSchema.parse(request.body);
    const candidates = await dependencies.database.getCapsuleCandidates(
      principal.tenantSubject,
      input.project_id,
      input.items.map((item) => item.job_id),
    );
    const byJob = Map.groupBy(candidates, (candidate) => candidate.job_id);
    const contentTypes = new Set(
      candidates.map((candidate) => candidate.input_type),
    );
    const parityShards =
      input.ecc_percent === 0
        ? 0
        : Math.max(1, Math.ceil((input.ecc_percent * 10) / 100));
    const protectedMetadataBytes = input.items.length * 384 + 64;
    const sectionCount = 3 + contentTypes.size + 1 + (parityShards > 0 ? 1 : 0);
    const fixedOverheadBytes =
      64 +
      sectionCount * 64 +
      protectedMetadataBytes +
      (parityShards > 0
        ? 12 + Math.ceil(protectedMetadataBytes / 10) * parityShards
        : 0);
    const plannerResult = await dependencies.capsulePlanner.plan({
      budget_bytes: input.budget_bytes,
      fixed_overhead_bytes: fixedOverheadBytes,
      items: input.items.map((item) => ({
        id: item.job_id,
        required: item.required,
        candidates: (byJob.get(item.job_id) ?? []).map((candidate) => {
          // postgres.js returns BIGINT columns as strings to preserve precision.
          // These values are bounded well below Number.MAX_SAFE_INTEGER by the
          // upload and capsule schemas, so normalize before doing byte math.
          const payloadBytes = Number(candidate.payload_bytes);
          const containerOverheadBytes = Number(
            candidate.container_overhead_bytes,
          );
          const streamBytes = payloadBytes + containerOverheadBytes + 10;
          const eccBytes =
            parityShards > 0 ? Math.ceil(streamBytes / 10) * parityShards : 0;
          return {
            id: candidate.candidate_id,
            bytes: streamBytes + eccBytes,
            utility: item.utility,
          };
        }),
      })),
    });
    dependencies.metrics.recordPlannerIteration(plannerResult.solver);
    const byCandidate = new Map(
      candidates.map((candidate) => [candidate.candidate_id, candidate]),
    );
    const selections = plannerResult.selections.map((selection) => {
      const candidate = selection.candidate_id
        ? byCandidate.get(selection.candidate_id)
        : undefined;
      return {
        ...selection,
        artifact_id: candidate?.artifact_id ?? null,
        content_type: candidate?.input_type ?? null,
        codec_id: candidate?.codec_id ?? null,
        codec_version: candidate?.codec_version ?? null,
        payload_bytes: Number(candidate?.payload_bytes ?? 0),
      };
    });
    const result = await dependencies.database.createCapsulePlan(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      idempotencyKey(request),
      input,
      plannerResult.solver,
      {
        ...plannerResult,
        fixed_overhead_bytes: fixedOverheadBytes,
        selections,
      },
    );
    return reply.status(result.created ? 201 : 200).send(result.plan);
  });

  app.get("/v1/capsule-plans/:id", async (request) => {
    const principal = await authorizedPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCapsulePlan(principal.tenantSubject, id);
  });

  app.post("/v1/capsules", async (request, reply) => {
    const principal = await authorizedPrincipal(request, "capsules:create");
    const input = createCapsuleSchema.parse(request.body);
    const result = await dependencies.database.createCapsuleJob(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      idempotencyKey(request),
      input,
    );
    if (result.created) {
      dependencies.metrics.recordJob("capsule");
    }
    return reply.status(202).send(result.capsule);
  });

  app.post("/v1/capsules/verify", async (request) => {
    const principal = await authorizedPrincipal(request, "capsules:read");
    const input = verifyCapsuleSchema.parse(request.body);
    const capsule = await dependencies.database.getCapsule(
      principal.tenantSubject,
      input.capsule_id,
    );
    if (capsule.project_id !== input.project_id) {
      throw new ApiProblem(
        404,
        "Capsule not found",
        "urn:smcp:problem:not-found",
      );
    }
    if (
      capsule.status !== "COMPLETED" ||
      !capsule.sha256_hex ||
      !capsule.merkle_root_hex ||
      capsule.actual_bytes === null
    ) {
      throw new ApiProblem(
        409,
        "Capsule has not completed build-time verification",
        "urn:smcp:problem:invalid-state",
      );
    }
    const actualBytes = Number(capsule.actual_bytes);
    const budgetBytes = Number(capsule.budget_bytes);
    return {
      valid: true,
      capsule_id: capsule.id,
      actual_bytes: actualBytes,
      budget_bytes: budgetBytes,
      within_budget: actualBytes <= budgetBytes,
      sha256: capsule.sha256_hex,
      merkle_root: capsule.merkle_root_hex,
      format: `${capsule.format_major}.${capsule.format_minor}`,
      verification_source: "build-time-rust-verifier",
      verified_at: capsule.completed_at,
    };
  });

  app.get("/v1/capsules/:id", async (request) => {
    const principal = await authorizedPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCapsule(principal.tenantSubject, id);
  });

  app.get("/v1/capsules/:id/manifest", async (request) => {
    const principal = await authorizedPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCapsuleManifest(
      principal.tenantSubject,
      id,
    );
  });

  app.get("/v1/capsules/:id/download", async (request) => {
    const principal = await authorizedPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    const capsule = await dependencies.database.getCapsule(
      principal.tenantSubject,
      id,
    );
    if (capsule.status !== "COMPLETED" || !capsule.object_key) {
      throw new ApiProblem(
        409,
        "Capsule is not ready for download",
        "urn:smcp:problem:invalid-state",
      );
    }
    return {
      capsule_id: id,
      sha256: capsule.sha256_hex,
      bytes: capsule.actual_bytes,
      download_url: await dependencies.storage.presignDownload(
        capsule.object_key,
      ),
      expires_in_seconds: config.SIGNED_URL_TTL_SECONDS,
    };
  });

  app.get("/v1/capsules", async (request) => {
    const principal = await authorizedPrincipal(request, "capsules:read");
    const {
      project_id: projectId,
      limit,
      offset,
    } = projectCollectionQuerySchema.parse(request.query);
    const page = await dependencies.database.listCapsules(
      principal.tenantSubject,
      projectId,
      limit,
      offset,
    );
    return { total_count: page.totalCount, limit, offset, data: page.data };
  });

  app.get("/v1/projects", async (request) => {
    const session = await sessionPrincipal(request);
    const { limit, offset } = paginationQuerySchema.parse(request.query);
    const page = await dependencies.database.listProjects(
      session.tenantSubject,
      limit,
      offset,
    );
    return { total_count: page.totalCount, limit, offset, data: page.data };
  });

  app.post("/v1/projects", async (request, reply) => {
    const requestIdempotencyKey = idempotencyKey(request);
    const session = await sessionPrincipal(request);
    const input = createProjectSchema.parse(request.body);
    const result = await dependencies.database.createProject(
      session.tenantSubject,
      session.actorSubject,
      request.id,
      requestIdempotencyKey,
      input,
    );
    return reply.status(result.created ? 201 : 200).send(result.project);
  });

  app.get("/v1/projects/:id/usage", async (request) => {
    const principal = await authorizedPrincipal(request, "jobs:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getProjectUsage(principal.tenantSubject, id);
  });

  app.patch("/v1/projects/:id/settings", async (request) => {
    const session = requireOrganizationAdmin(await sessionPrincipal(request));
    const { id } = resourceIdParamsSchema.parse(request.params);
    const input = updateProjectSettingsSchema.parse(request.body);
    return dependencies.database.updateProjectSettings(
      session.tenantSubject,
      session.actorSubject,
      request.id,
      id,
      input,
    );
  });

  app.get("/v1/api-keys", async (request) => {
    const session = requireOrganizationAdmin(await sessionPrincipal(request));
    const page = await dependencies.clerk.listApiKeys(session.tenantSubject);
    return {
      total_count: page.totalCount,
      data: page.data.map(({ secret: _secret, ...metadata }) => metadata),
    };
  });

  app.post("/v1/api-keys", async (request, reply) => {
    const requestIdempotencyKey = idempotencyKey(request);
    const session = requireOrganizationAdmin(await sessionPrincipal(request));
    const input = createApiKeySchema.parse(request.body);
    const secondsUntilExpiration = Math.floor(
      (new Date(input.expires_at).getTime() - Date.now()) / 1000,
    );
    if (secondsUntilExpiration < 60) {
      throw new ApiProblem(
        400,
        "API key expiry must be at least 60 seconds in the future",
        "urn:smcp:problem:invalid-expiry",
      );
    }
    const normalizedInput = {
      ...input,
      scopes: [...new Set(input.scopes)].sort(),
    };
    const route = "POST /v1/api-keys";
    const claim = await dependencies.database.claimExternalMutation(
      session.tenantSubject,
      route,
      requestIdempotencyKey,
      normalizedInput,
    );
    if (claim.state === "pending") {
      throw new ApiProblem(
        409,
        "An API-key creation with this idempotency key is still in progress",
        "urn:smcp:problem:idempotency-in-progress",
      );
    }
    if (claim.state === "completed") {
      throw new ApiProblem(
        409,
        "This idempotent API-key creation already completed; its one-time secret cannot be replayed",
        "urn:smcp:problem:one-time-secret-already-issued",
      );
    }

    const existing = (
      await dependencies.clerk.listApiKeys(session.tenantSubject)
    ).data.find((key) => key.claims?.smcp_operation_id === claim.operationId);
    const key =
      existing ??
      (await dependencies.clerk.createApiKey({
        name: normalizedInput.name,
        subject: session.tenantSubject,
        createdBy: session.actorSubject,
        scopes: normalizedInput.scopes,
        claims: {
          smcp_issued: true,
          smcp_operation_id: claim.operationId,
        },
        secondsUntilExpiration,
      }));
    const secret =
      key.secret ?? (await dependencies.clerk.getApiKeySecret(key.id));
    const { secret: _secret, ...metadata } = key;
    await dependencies.database.completeExternalApiKeyCreation(
      session.tenantSubject,
      session.actorSubject,
      request.id,
      route,
      requestIdempotencyKey,
      claim.operationId,
      key.id,
      metadata,
    );
    return reply.status(201).send({ ...metadata, secret });
  });

  app.post("/v1/api-keys/:id/rotate", async (request, reply) => {
    const requestIdempotencyKey = idempotencyKey(request);
    const session = requireOrganizationAdmin(await sessionPrincipal(request));
    const { id } = apiKeyIdParamsSchema.parse(request.params);
    const { overlap_seconds: overlapSeconds } = rotateApiKeySchema.parse(
      request.body ?? {},
    );
    const oldKey = await dependencies.clerk.getApiKey(id);
    if (oldKey.subject !== session.tenantSubject) {
      throw new ApiProblem(
        404,
        "API key not found",
        "urn:smcp:problem:not-found",
      );
    }
    const route = "/v1/api-keys/:id/rotate";
    const claim = await dependencies.database.claimExternalMutation(
      session.tenantSubject,
      route,
      requestIdempotencyKey,
      { id: oldKey.id, overlap_seconds: overlapSeconds },
    );
    if (claim.state === "completed") {
      throw new ApiProblem(
        409,
        "Rotation already completed; the one-time replacement secret cannot be replayed",
        "urn:smcp:problem:rotation-already-created",
      );
    }
    if (claim.state === "pending") {
      throw new ApiProblem(
        409,
        "Rotation is still being reconciled; retry later with the same Idempotency-Key",
        "urn:smcp:problem:idempotency-pending",
      );
    }
    if (oldKey.revoked) {
      throw new ApiProblem(
        404,
        "API key not found",
        "urn:smcp:problem:not-found",
      );
    }
    const remainingSeconds = oldKey.expiration
      ? Math.max(60, Math.floor((oldKey.expiration - Date.now()) / 1000))
      : 31_536_000;
    const existing = (
      await dependencies.clerk.listApiKeys(session.tenantSubject)
    ).data.find(
      (key) =>
        key.claims?.smcp_rotation_operation_id === claim.operationId &&
        key.claims?.rotated_from === oldKey.id,
    );
    if (
      !existing &&
      (await dependencies.database.apiKeyRotationExists(
        session.tenantSubject,
        oldKey.id,
      ))
    ) {
      throw new ApiProblem(
        409,
        "This key has already been rotated",
        "urn:smcp:problem:rotation-already-created",
      );
    }
    const replacement =
      existing ??
      (await dependencies.clerk.createApiKey({
        name: `${oldKey.name} (rotated)`,
        subject: session.tenantSubject,
        createdBy: session.actorSubject,
        scopes: oldKey.scopes,
        claims: {
          smcp_issued: true,
          rotated_from: oldKey.id,
          smcp_rotation_operation_id: claim.operationId,
        },
        secondsUntilExpiration: remainingSeconds,
      }));
    const secret =
      replacement.secret ??
      (await dependencies.clerk.getApiKeySecret(replacement.id));
    const { secret: _secret, ...replacementMetadata } = replacement;
    const revokeAt = new Date(Date.now() + overlapSeconds * 1_000);
    let rotation;
    try {
      rotation = await dependencies.database.completeExternalApiKeyRotation(
        session.tenantSubject,
        session.actorSubject,
        request.id,
        route,
        requestIdempotencyKey,
        claim.operationId,
        oldKey.id,
        replacement.id,
        revokeAt,
        {
          ...replacementMetadata,
          rotation: { old_key_id: oldKey.id, revoke_at: revokeAt },
        },
      );
    } catch (error) {
      if (
        error instanceof ApiProblem &&
        error.type === "urn:smcp:problem:rotation-already-created"
      ) {
        await dependencies.clerk.revokeApiKey(
          replacement.id,
          "Conflicting rotation operation",
        );
      }
      throw error;
    }
    let revocationPending = overlapSeconds > 0;
    if (overlapSeconds === 0) {
      try {
        await dependencies.clerk.revokeApiKey(
          oldKey.id,
          `Rotated to ${replacement.id}`,
        );
        await dependencies.database.markApiKeyRotationRevoked(rotation.id);
        revocationPending = false;
      } catch {
        // The durable due row remains claimable by the scheduler.
        revocationPending = true;
      }
    }
    return reply.status(201).send({
      ...replacementMetadata,
      secret,
      rotation: {
        old_key_id: oldKey.id,
        revoke_at: rotation.revoke_at,
        revocation_pending: revocationPending,
      },
    });
  });

  app.delete("/v1/api-keys/:id", async (request, reply) => {
    const session = requireOrganizationAdmin(await sessionPrincipal(request));
    const { id } = apiKeyIdParamsSchema.parse(request.params);
    const key = await dependencies.clerk.getApiKey(id);
    if (key.subject !== session.tenantSubject) {
      throw new ApiProblem(
        404,
        "API key not found",
        "urn:smcp:problem:not-found",
      );
    }
    await dependencies.clerk.revokeApiKey(
      id,
      `Revoked by ${session.actorSubject}`,
    );
    await dependencies.database.auditApiKeyRevocation(
      session.tenantSubject,
      session.actorSubject,
      request.id,
      id,
    );
    return reply.status(204).send();
  });

  app.post("/v1/webhooks", async (request, reply) => {
    const principal = await authorizedPrincipal(request, "webhooks:manage");
    const input = createWebhookEndpointSchema.parse(request.body);
    await resolvePublicWebhookUrl(input.url);
    const secret = `whsec_${randomBytes(32).toString("base64url")}`;
    const result = await dependencies.database.createWebhookEndpoint(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      idempotencyKey(request),
      input,
      webhookSecretBox.encrypt(secret),
    );
    return reply.status(result.created ? 201 : 200).send({
      ...result.endpoint,
      secret: result.created ? secret : undefined,
      secret_available: result.created,
    });
  });

  app.get("/v1/webhooks", async (request) => {
    const principal = await authorizedPrincipal(request, "webhooks:manage");
    const { project_id: projectId } = projectIdQuerySchema.parse(request.query);
    const data = await dependencies.database.listWebhookEndpoints(
      principal.tenantSubject,
      projectId,
    );
    return { total_count: data.length, data };
  });

  app.delete("/v1/webhooks/:id", async (request, reply) => {
    const principal = await authorizedPrincipal(request, "webhooks:manage");
    const { id } = resourceIdParamsSchema.parse(request.params);
    await dependencies.database.disableWebhookEndpoint(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      id,
    );
    return reply.status(204).send();
  });

  app.post("/v1/uploads/presign", async (request, reply) => {
    const requestIdempotencyKey = idempotencyKey(request);
    const principal = await authorizedPrincipal(request, "jobs:create");
    const input = presignUploadSchema.parse(request.body);
    if (input.bytes > config.MAX_UPLOAD_BYTES) {
      throw new ApiProblem(
        413,
        "Upload exceeds configured byte limit",
        "urn:smcp:problem:upload-too-large",
      );
    }
    const sourceId = randomUUID();
    const objectKey = `${safeKeySegment(principal.tenantSubject)}/${input.project_id}/sources/${sourceId}/${safeKeySegment(input.filename)}`;
    const expiresAt = new Date(
      Date.now() + config.SIGNED_URL_TTL_SECONDS * 1000,
    );
    const result = await dependencies.database.createSourceObject(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      requestIdempotencyKey,
      input,
      objectKey,
      expiresAt,
    );
    const uploadUrl = await dependencies.storage.presignUpload(
      result.source.object_key,
      input.content_type,
      input.bytes,
    );
    return reply.status(result.created ? 201 : 200).send({
      source_object_id: result.source.id,
      upload_url: uploadUrl,
      method: "PUT",
      required_headers: {
        "content-type": input.content_type,
        "content-length": String(input.bytes),
        "x-amz-server-side-encryption": "AES256",
      },
      expires_at: result.source.upload_expires_at.toISOString(),
    });
  });

  app.post("/v1/compressions", async (request, reply) => {
    const principal = await authorizedPrincipal(request, "jobs:create");
    const input = createCompressionSchema.parse(request.body);
    if (input.profile === "semantic") {
      throw new ApiProblem(
        422,
        "Semantic profile is unavailable until a verified decoder and immutable weights are enabled",
        "urn:smcp:problem:semantic-profile-unavailable",
      );
    }
    const result = await dependencies.database.createCompressionJob(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      idempotencyKey(request),
      input,
    );
    if (result.created) {
      dependencies.metrics.recordJob("compression");
    }
    return reply.status(202).send(result.job);
  });

  app.get("/v1/compressions", async (request) => {
    const principal = await authorizedPrincipal(request, "jobs:read");
    const {
      project_id: projectId,
      limit,
      offset,
    } = projectCollectionQuerySchema.parse(request.query);
    const page = await dependencies.database.listCompressionJobs(
      principal.tenantSubject,
      projectId,
      limit,
      offset,
    );
    return { total_count: page.totalCount, limit, offset, data: page.data };
  });

  app.get("/v1/compressions/:id", async (request) => {
    const principal = await authorizedPrincipal(request, "jobs:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCompressionJob(principal.tenantSubject, id);
  });

  app.get("/v1/compressions/:id/candidates", async (request) => {
    const principal = await authorizedPrincipal(request, "jobs:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return {
      data: await dependencies.database.listCandidates(
        principal.tenantSubject,
        id,
      ),
    };
  });

  app.get("/v1/artifacts/:id/download", async (request) => {
    const principal = await authorizedPrincipal(request, "artifacts:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    const artifact = await dependencies.database.getArtifact(
      principal.tenantSubject,
      id,
    );
    return {
      artifact_id: artifact.id,
      sha256: artifact.sha256_hex,
      bytes: artifact.bytes,
      download_url: await dependencies.storage.presignDownload(
        artifact.object_key,
      ),
      expires_in_seconds: config.SIGNED_URL_TTL_SECONDS,
    };
  });

  app.get("/v1/artifacts", async (request) => {
    const principal = await authorizedPrincipal(request, "artifacts:read");
    const {
      project_id: projectId,
      limit,
      offset,
    } = projectCollectionQuerySchema.parse(request.query);
    const page = await dependencies.database.listArtifacts(
      principal.tenantSubject,
      projectId,
      limit,
      offset,
    );
    return { total_count: page.totalCount, limit, offset, data: page.data };
  });

  app.post("/v1/decompressions", async (request, reply) => {
    const principal = await authorizedPrincipal(
      request,
      "decompressions:create",
    );
    const input = createDecompressionSchema.parse(request.body);
    const result = await dependencies.database.createDecompressionJob(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      idempotencyKey(request),
      input,
    );
    if (result.created) {
      dependencies.metrics.recordJob("decompression");
    }
    return reply.status(202).send(result.job);
  });

  app.get("/v1/decompressions/:id", async (request) => {
    const principal = await authorizedPrincipal(request, "artifacts:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    const job = await dependencies.database.getDecompressionJob(
      principal.tenantSubject,
      id,
    );
    return {
      ...job,
      ...(job.status === "COMPLETED" && job.output_object_key
        ? {
            download_url: await dependencies.storage.presignDownload(
              job.output_object_key,
            ),
            expires_in_seconds: config.SIGNED_URL_TTL_SECONDS,
          }
        : {}),
    };
  });

  app.post("/v1/compressions/:id/cancel", async (request, reply) => {
    const cancellationIdempotencyKey = idempotencyKey(request);
    const principal = await authorizedPrincipal(request, "jobs:cancel");
    const { id } = resourceIdParamsSchema.parse(request.params);
    const job = await dependencies.database.cancelCompressionJob(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      cancellationIdempotencyKey,
      id,
    );
    return reply.status(202).send(job);
  });

  app.addHook("onClose", async () => {
    await Promise.all([
      dependencies.database.close(),
      dependencies.queue.close(),
      dependencies.keyRotationScheduler.close(),
      dependencies.webhookDispatcher.close(),
      dependencies.jobOutboxPublisher.close(),
      dependencies.rateLimiter.close(),
    ]);
  });

  return { app, dependencies };
}
