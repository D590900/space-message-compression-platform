import { randomUUID } from "node:crypto";

import rateLimit from "@fastify/rate-limit";
import {
  createApiKeySchema,
  createCapsulePlanSchema,
  createCapsuleSchema,
  createCompressionSchema,
  createDecompressionSchema,
  createProjectSchema,
  idempotencyKeySchema,
  presignUploadSchema,
  resourceIdParamsSchema,
  rotateApiKeySchema,
  verifyCapsuleSchema,
  type ApiScope,
} from "@smcp/schemas";
import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";

import {
  type ClerkGateway,
  ProductionClerkGateway,
  requireApiKey,
  requireSession,
} from "./auth.js";
import type { ApiConfig } from "./config.js";
import {
  type CapsulePlannerGateway,
  RustCapsulePlanner,
} from "./capsule-planner.js";
import { Database } from "./database.js";
import { toWebRequest } from "./http-request.js";
import { ApiProblem, registerProblemHandler } from "./problem.js";
import { JobQueue } from "./queue.js";
import { ObjectStorage } from "./storage.js";

export type AppDependencies = {
  database: Database;
  queue: JobQueue;
  storage: ObjectStorage;
  clerk: ClerkGateway;
  capsulePlanner: CapsulePlannerGateway;
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
  const dependencies: AppDependencies = {
    database: overrides.database ?? new Database(config.DATABASE_URL),
    queue: overrides.queue ?? new JobQueue(config.VALKEY_URL),
    storage: overrides.storage ?? new ObjectStorage(config),
    clerk: overrides.clerk ?? new ProductionClerkGateway(config),
    capsulePlanner:
      overrides.capsulePlanner ??
      new RustCapsulePlanner(config.CAPSULE_CLI_PATH),
  };

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
    keyGenerator: (request) =>
      request.headers.authorization?.slice(-24) ?? request.ip,
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

  const apiPrincipal = async (request: FastifyRequest, scope: ApiScope) =>
    requireApiKey(dependencies.clerk, request.headers.authorization, scope);

  app.get("/v1/codecs", async (request) => {
    await apiPrincipal(request, "codecs:read");
    const data = await dependencies.database.listCodecCapabilities();
    return { total_count: data.length, data };
  });

  app.get("/v1/models", async (request) => {
    await apiPrincipal(request, "codecs:read");
    const data = await dependencies.database.listModelManifests();
    return { total_count: data.length, data };
  });

  app.post("/v1/capsule-plans", async (request, reply) => {
    const principal = await apiPrincipal(request, "capsules:plan");
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
          const streamBytes =
            candidate.payload_bytes + candidate.container_overhead_bytes + 10;
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
        payload_bytes: candidate?.payload_bytes ?? 0,
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
    const principal = await apiPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCapsulePlan(principal.tenantSubject, id);
  });

  app.post("/v1/capsules", async (request, reply) => {
    const principal = await apiPrincipal(request, "capsules:create");
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
      await dependencies.queue.publishCapsule(
        result.capsule.id,
        principal.tenantSubject,
      );
    }
    return reply.status(202).send(result.capsule);
  });

  app.post("/v1/capsules/verify", async (request) => {
    const principal = await apiPrincipal(request, "capsules:read");
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
    return {
      valid: true,
      capsule_id: capsule.id,
      actual_bytes: capsule.actual_bytes,
      budget_bytes: capsule.budget_bytes,
      within_budget: capsule.actual_bytes <= capsule.budget_bytes,
      sha256: capsule.sha256_hex,
      merkle_root: capsule.merkle_root_hex,
      format: `${capsule.format_major}.${capsule.format_minor}`,
      verification_source: "build-time-rust-verifier",
      verified_at: capsule.completed_at,
    };
  });

  app.get("/v1/capsules/:id", async (request) => {
    const principal = await apiPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCapsule(principal.tenantSubject, id);
  });

  app.get("/v1/capsules/:id/manifest", async (request) => {
    const principal = await apiPrincipal(request, "capsules:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCapsuleManifest(
      principal.tenantSubject,
      id,
    );
  });

  app.get("/v1/capsules/:id/download", async (request) => {
    const principal = await apiPrincipal(request, "capsules:read");
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

  app.post("/v1/projects", async (request, reply) => {
    idempotencyKey(request);
    const session = await requireSession(
      dependencies.clerk,
      toWebRequest(request, config.API_ORIGIN),
    );
    const input = createProjectSchema.parse(request.body);
    const project = await dependencies.database.createProject(
      session.tenantSubject,
      session.actorSubject,
      request.id,
      input,
    );
    return reply.status(201).send(project);
  });

  app.get("/v1/api-keys", async (request) => {
    const session = await requireSession(
      dependencies.clerk,
      toWebRequest(request, config.API_ORIGIN),
    );
    const page = await dependencies.clerk.listApiKeys(session.tenantSubject);
    return {
      total_count: page.totalCount,
      data: page.data.map(({ secret: _secret, ...metadata }) => metadata),
    };
  });

  app.post("/v1/api-keys", async (request, reply) => {
    const session = await requireSession(
      dependencies.clerk,
      toWebRequest(request, config.API_ORIGIN),
    );
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
    const key = await dependencies.clerk.createApiKey({
      name: input.name,
      subject: session.tenantSubject,
      createdBy: session.actorSubject,
      scopes: [...new Set(input.scopes)].sort(),
      claims: { smcp_issued: true },
      secondsUntilExpiration,
    });
    if (!key.secret)
      throw new Error("Clerk did not return a one-time API-key secret");
    return reply.status(201).send(key);
  });

  app.post("/v1/api-keys/:id/rotate", async (request, reply) => {
    idempotencyKey(request);
    const session = await requireSession(
      dependencies.clerk,
      toWebRequest(request, config.API_ORIGIN),
    );
    const { id } = resourceIdParamsSchema.parse(request.params);
    const { overlap_seconds: overlapSeconds } = rotateApiKeySchema.parse(
      request.body ?? {},
    );
    if (overlapSeconds !== 0) {
      throw new ApiProblem(
        422,
        "Delayed revocation requires the rotation scheduler",
        "urn:smcp:problem:capability-disabled",
      );
    }
    const oldKey = await dependencies.clerk.getApiKey(id);
    if (oldKey.subject !== session.tenantSubject || oldKey.revoked) {
      throw new ApiProblem(
        404,
        "API key not found",
        "urn:smcp:problem:not-found",
      );
    }
    const remainingSeconds = oldKey.expiration
      ? Math.max(60, Math.floor((oldKey.expiration - Date.now()) / 1000))
      : 31_536_000;
    const replacement = await dependencies.clerk.createApiKey({
      name: `${oldKey.name} (rotated)`,
      subject: session.tenantSubject,
      createdBy: session.actorSubject,
      scopes: oldKey.scopes,
      claims: { smcp_issued: true, rotated_from: oldKey.id },
      secondsUntilExpiration: remainingSeconds,
    });
    await dependencies.clerk.revokeApiKey(
      oldKey.id,
      `Rotated to ${replacement.id}`,
    );
    return reply.status(201).send(replacement);
  });

  app.delete("/v1/api-keys/:id", async (request, reply) => {
    const session = await requireSession(
      dependencies.clerk,
      toWebRequest(request, config.API_ORIGIN),
    );
    const { id } = resourceIdParamsSchema.parse(request.params);
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
    return reply.status(204).send();
  });

  app.post("/v1/uploads/presign", async (request, reply) => {
    idempotencyKey(request);
    const principal = await apiPrincipal(request, "jobs:create");
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
    const source = await dependencies.database.createSourceObject(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      input,
      objectKey,
      expiresAt,
    );
    const uploadUrl = await dependencies.storage.presignUpload(
      objectKey,
      input.content_type,
      input.bytes,
    );
    return reply.status(201).send({
      source_object_id: source.id,
      upload_url: uploadUrl,
      method: "PUT",
      required_headers: {
        "content-type": input.content_type,
        "content-length": String(input.bytes),
        "x-amz-server-side-encryption": "AES256",
      },
      expires_at: expiresAt.toISOString(),
    });
  });

  app.post("/v1/compressions", async (request, reply) => {
    const principal = await apiPrincipal(request, "jobs:create");
    const input = createCompressionSchema.parse(request.body);
    const result = await dependencies.database.createCompressionJob(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      idempotencyKey(request),
      input,
    );
    if (result.created) {
      await dependencies.queue.publishCompression(
        result.job.id,
        principal.tenantSubject,
      );
    }
    return reply.status(202).send(result.job);
  });

  app.get("/v1/compressions/:id", async (request) => {
    const principal = await apiPrincipal(request, "jobs:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return dependencies.database.getCompressionJob(principal.tenantSubject, id);
  });

  app.get("/v1/compressions/:id/candidates", async (request) => {
    const principal = await apiPrincipal(request, "jobs:read");
    const { id } = resourceIdParamsSchema.parse(request.params);
    return {
      data: await dependencies.database.listCandidates(
        principal.tenantSubject,
        id,
      ),
    };
  });

  app.get("/v1/artifacts/:id/download", async (request) => {
    const principal = await apiPrincipal(request, "artifacts:read");
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

  app.post("/v1/decompressions", async (request, reply) => {
    const principal = await apiPrincipal(request, "decompressions:create");
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
      await dependencies.queue.publishDecompression(
        result.job.id,
        principal.tenantSubject,
      );
    }
    return reply.status(202).send(result.job);
  });

  app.get("/v1/decompressions/:id", async (request) => {
    const principal = await apiPrincipal(request, "artifacts:read");
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
    idempotencyKey(request);
    const principal = await apiPrincipal(request, "jobs:cancel");
    const { id } = resourceIdParamsSchema.parse(request.params);
    const job = await dependencies.database.cancelCompressionJob(
      principal.tenantSubject,
      principal.actorSubject,
      principal.keyId,
      request.id,
      id,
    );
    return reply.status(202).send(job);
  });

  app.addHook("onClose", async () => {
    await Promise.all([
      dependencies.database.close(),
      dependencies.queue.close(),
    ]);
  });

  return { app, dependencies };
}
