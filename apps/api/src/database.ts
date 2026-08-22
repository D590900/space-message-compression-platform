import { createHash, randomUUID } from "node:crypto";

import type {
  ContentType,
  CreateCapsulePlanInput,
  CreateCapsuleInput,
  CreateCompressionInput,
  CreateDecompressionInput,
  CreateProjectInput,
  CreateWebhookEndpointInput,
  JobStatus,
  PresignUploadInput,
  Profile,
} from "@smcp/schemas";
import postgres from "postgres";

import { ApiProblem } from "./problem.js";

export type ProjectRecord = {
  id: string;
  tenant_subject: string;
  name: string;
  created_at: Date;
};

export type SourceObjectRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  object_key: string;
  declared_mime: string;
  expected_bytes: number;
  upload_expires_at: Date;
};

export type CompressionJobRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  input_type: ContentType;
  profile: Profile;
  target_bytes: number | null;
  status: JobStatus;
  source_object_id: string;
  selected_candidate_id: string | null;
  requested_at: Date;
  completed_at: Date | null;
  error_code: string | null;
};

export type CandidateRecord = {
  id: string;
  codec_id: string;
  codec_version: string;
  payload_bytes: number;
  container_overhead_bytes: number;
  quality_metrics: Record<string, unknown>;
  quality_gate_passed: boolean;
  determinism_status: string;
};

export type ArtifactRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  job_id: string;
  candidate_id: string;
  kind: string;
  object_key: string;
  bytes: number;
  sha256_hex: string;
};

export type DecompressionJobRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  artifact_id: string;
  status: string;
  output_object_key: string | null;
  output_bytes: number | null;
  output_sha256_hex: string | null;
  verified: boolean | null;
  error_code: string | null;
  requested_at: Date;
  completed_at: Date | null;
};

export type CodecCapabilityRecord = {
  id: string;
  version: string;
  content_type: ContentType;
  implementation_sha256: string;
  deterministic: boolean;
  enabled: boolean;
  disabled_reason: string | null;
  capability: Record<string, unknown>;
};

export type ModelManifestRecord = {
  id: string;
  version: string;
  source_uri: string;
  code_commit: string;
  weights_sha256: string;
  config_sha256: string;
  license_code: string;
  license_weights: string;
  input_contract: string;
  decoder_image_digest: string;
  enabled: boolean;
};

export type CapsuleCandidateRecord = {
  job_id: string;
  input_type: ContentType;
  candidate_id: string;
  artifact_id: string;
  codec_id: string;
  codec_version: string;
  payload_bytes: number;
  container_overhead_bytes: number;
};

export type CapsulePlanRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  budget_bytes: number;
  ecc_percent: number;
  status: string;
  solver: string;
  report: Record<string, unknown>;
  created_at: Date;
};

export type CapsuleRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  plan_id: string;
  budget_bytes: number;
  actual_bytes: number | null;
  object_key: string | null;
  sha256_hex: string | null;
  merkle_root_hex: string | null;
  format_major: number | null;
  format_minor: number | null;
  status: string;
  error_code: string | null;
  build_options: Record<string, unknown>;
  created_at: Date;
  completed_at: Date | null;
};

export type ApiKeyRotationRecord = {
  id: string;
  tenant_subject: string;
  old_key_id: string;
  new_key_id: string;
  revoke_at: Date;
  attempt: number;
};

export type WebhookEndpointRecord = {
  id: string;
  tenant_subject: string;
  project_id: string;
  url: string;
  event_types: string[];
  enabled: boolean;
  created_at: Date;
  disabled_at: Date | null;
};

export type WebhookDeliveryClaim = {
  id: string;
  tenant_subject: string;
  endpoint_id: string;
  event_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  attempt: number;
  url: string;
  secret_ciphertext: Buffer;
};

export type ProjectUsageRecord = {
  project_id: string;
  period_start: Date;
  counters: Record<string, number>;
  active_jobs: number;
  quotas: {
    max_monthly_input_bytes: number;
    max_monthly_jobs: number;
    max_concurrent_jobs: number;
    max_monthly_capsules: number;
  };
};

export class Database {
  private readonly sql;

  public constructor(databaseUrl: string) {
    this.sql = postgres(databaseUrl, {
      max: 10,
      idle_timeout: 20,
      connect_timeout: 10,
      transform: { undefined: null },
    });
  }

  public async close(): Promise<void> {
    await this.sql.end({ timeout: 5 });
  }

  public async ready(): Promise<boolean> {
    await this.sql`SELECT 1`;
    return true;
  }

  public async listCodecCapabilities(): Promise<CodecCapabilityRecord[]> {
    return this.sql<CodecCapabilityRecord[]>`
      SELECT id, version, content_type,
             encode(implementation_sha256, 'hex') AS implementation_sha256,
             deterministic, enabled, disabled_reason, capability
      FROM codec_registry
      ORDER BY content_type, id, version
    `;
  }

  public async listModelManifests(): Promise<ModelManifestRecord[]> {
    return this.sql<ModelManifestRecord[]>`
      SELECT id, version, source_uri, code_commit,
             encode(weights_sha256, 'hex') AS weights_sha256,
             encode(config_sha256, 'hex') AS config_sha256,
             license_code, license_weights, input_contract,
             decoder_image_digest, enabled
      FROM model_registry
      ORDER BY id, version
    `;
  }

  public async getCapsuleCandidates(
    tenantSubject: string,
    projectId: string,
    jobIds: string[],
  ): Promise<CapsuleCandidateRecord[]> {
    await this.assertProject(tenantSubject, projectId);
    const rows = await this.sql<CapsuleCandidateRecord[]>`
      SELECT j.id AS job_id, j.input_type, c.id AS candidate_id,
             a.id AS artifact_id, c.codec_id, c.codec_version,
             c.payload_bytes, c.container_overhead_bytes
      FROM compression_jobs j
      JOIN encoding_candidates c
        ON c.job_id = j.id AND c.tenant_subject = j.tenant_subject
      JOIN artifacts a
        ON a.candidate_id = c.id AND a.tenant_subject = c.tenant_subject
      WHERE j.tenant_subject = ${tenantSubject}
        AND j.project_id = ${projectId}
        AND j.id = ANY(${jobIds})
        AND j.status = 'COMPLETED'
        AND c.quality_gate_passed = true
      ORDER BY j.id, c.payload_bytes, c.id
    `;
    const found = new Set(rows.map((row) => row.job_id));
    if (jobIds.some((id) => !found.has(id))) {
      throw new ApiProblem(
        422,
        "Every capsule item must reference a completed job with a quality-gated candidate",
        "urn:smcp:problem:capsule-item-unavailable",
      );
    }
    return rows;
  }

  public async createCapsulePlan(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    idempotencyKey: string,
    input: CreateCapsulePlanInput,
    solver: string,
    report: Record<string, unknown>,
  ): Promise<{ plan: CapsulePlanRecord; created: boolean }> {
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();
    return this.sql.begin(async (transaction) => {
      const previous = await transaction<CapsulePlanRecord[]>`
        SELECT id, tenant_subject, project_id, budget_bytes, ecc_percent,
               status, solver, report, created_at
        FROM capsule_plans
        WHERE tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const matches = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM capsule_plans WHERE id = ${previous[0].id}
        `;
        if (!matches[0]?.matches) {
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        }
        return { plan: previous[0], created: false };
      }
      const id = randomUUID();
      const rows = await transaction<CapsulePlanRecord[]>`
        INSERT INTO capsule_plans (
          id, tenant_subject, project_id, budget_bytes, ecc_percent,
          status, solver, report, idempotency_key, request_fingerprint
        ) VALUES (
          ${id}, ${tenantSubject}, ${input.project_id}, ${input.budget_bytes},
          ${input.ecc_percent}, 'COMPLETED', ${solver},
          ${transaction.json(report as postgres.JSONValue)},
          ${idempotencyKey}, ${fingerprint}
        )
        RETURNING id, tenant_subject, project_id, budget_bytes, ecc_percent,
                  status, solver, report, created_at
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, api_key_id, action,
          resource_type, resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, ${actorSubject}, ${apiKeyId},
          'capsule_plan.created', 'capsule_plan', ${id}, ${requestId}, 'success'
        )
      `;
      return { plan: rows[0]!, created: true };
    });
  }

  public async getCapsulePlan(
    tenantSubject: string,
    id: string,
  ): Promise<CapsulePlanRecord> {
    const rows = await this.sql<CapsulePlanRecord[]>`
      SELECT id, tenant_subject, project_id, budget_bytes, ecc_percent,
             status, solver, report, created_at
      FROM capsule_plans
      WHERE tenant_subject = ${tenantSubject} AND id = ${id}
    `;
    if (!rows[0])
      throw new ApiProblem(
        404,
        "Capsule plan not found",
        "urn:smcp:problem:not-found",
      );
    return rows[0];
  }

  public async createCapsuleJob(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    idempotencyKey: string,
    input: CreateCapsuleInput,
  ): Promise<{ capsule: CapsuleRecord; created: boolean }> {
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();
    return this.sql.begin(async (transaction) => {
      const previous = await transaction<CapsuleRecord[]>`
        SELECT id, tenant_subject, project_id, plan_id, budget_bytes,
               actual_bytes, object_key,
               CASE WHEN sha256 IS NULL THEN NULL ELSE encode(sha256, 'hex') END AS sha256_hex,
               CASE WHEN merkle_root IS NULL THEN NULL ELSE encode(merkle_root, 'hex') END AS merkle_root_hex,
               format_major, format_minor, status, error_code, build_options,
               created_at, completed_at
        FROM capsules
        WHERE tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const matches = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM capsules WHERE id = ${previous[0].id}
        `;
        if (!matches[0]?.matches) {
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        }
        return { capsule: previous[0], created: false };
      }
      const plans = await transaction<CapsulePlanRecord[]>`
        SELECT id, tenant_subject, project_id, budget_bytes, ecc_percent,
               status, solver, report, created_at
        FROM capsule_plans
        WHERE id = ${input.plan_id}
          AND tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND status = 'COMPLETED'
      `;
      const plan = plans[0];
      if (!plan) {
        throw new ApiProblem(
          404,
          "Completed capsule plan not found",
          "urn:smcp:problem:not-found",
        );
      }
      await transaction`
        SELECT pg_advisory_xact_lock(
          hashtextextended(${`${tenantSubject}:${input.project_id}`}, 0)
        )
      `;
      const quota = await transaction<
        { max_monthly_capsules: number; used_capsules: number }[]
      >`
        SELECT q.max_monthly_capsules,
               COALESCE(u.value, 0) AS used_capsules
        FROM project_quotas q
        LEFT JOIN usage_counters u
          ON u.tenant_subject = q.tenant_subject
         AND u.project_id = q.project_id
         AND u.period_start = date_trunc('month', now())
         AND u.metric = 'capsules'
        WHERE q.tenant_subject = ${tenantSubject} AND q.project_id = ${input.project_id}
      `;
      if (
        !quota[0] ||
        Number(quota[0].used_capsules) >= Number(quota[0].max_monthly_capsules)
      )
        throw new ApiProblem(
          429,
          "Project monthly capsule quota exceeded",
          "urn:smcp:problem:quota-exceeded",
        );
      const id = randomUUID();
      const buildOptions = {
        ecc_percent: Number(plan.ecc_percent),
        pad_to_budget: input.pad_to_budget,
      };
      const rows = await transaction<CapsuleRecord[]>`
        INSERT INTO capsules (
          id, tenant_subject, project_id, plan_id, budget_bytes,
          status, idempotency_key, request_fingerprint, build_options
        ) VALUES (
          ${id}, ${tenantSubject}, ${input.project_id}, ${input.plan_id},
          ${plan.budget_bytes}, 'PENDING', ${idempotencyKey}, ${fingerprint},
          ${transaction.json(buildOptions)}
        )
        RETURNING id, tenant_subject, project_id, plan_id, budget_bytes,
                  actual_bytes, object_key, NULL::text AS sha256_hex,
                  NULL::text AS merkle_root_hex, format_major, format_minor,
                  status, error_code, build_options, created_at, completed_at
      `;
      await transaction`
        INSERT INTO usage_counters (
          tenant_subject, project_id, period_start, metric, value
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, date_trunc('month', now()),
          'capsules', 1
        )
        ON CONFLICT (tenant_subject, project_id, period_start, metric)
        DO UPDATE SET value = usage_counters.value + 1
      `;
      await transaction`
        INSERT INTO outbox_events (
          tenant_subject, project_id, topic, aggregate_id, payload
        )
        VALUES (
          ${tenantSubject}, ${input.project_id}, 'capsule.requested', ${id},
          ${transaction.json({ capsule_id: id, tenant_subject: tenantSubject })}
        )
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, api_key_id, action,
          resource_type, resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, ${actorSubject}, ${apiKeyId},
          'capsule.created', 'capsule', ${id}, ${requestId}, 'success'
        )
      `;
      return { capsule: rows[0]!, created: true };
    });
  }

  public async getCapsule(
    tenantSubject: string,
    id: string,
  ): Promise<CapsuleRecord> {
    const rows = await this.sql<CapsuleRecord[]>`
      SELECT id, tenant_subject, project_id, plan_id, budget_bytes,
             actual_bytes, object_key,
             CASE WHEN sha256 IS NULL THEN NULL ELSE encode(sha256, 'hex') END AS sha256_hex,
             CASE WHEN merkle_root IS NULL THEN NULL ELSE encode(merkle_root, 'hex') END AS merkle_root_hex,
             format_major, format_minor, status, error_code, build_options,
             created_at, completed_at
      FROM capsules
      WHERE tenant_subject = ${tenantSubject} AND id = ${id}
    `;
    if (!rows[0])
      throw new ApiProblem(
        404,
        "Capsule not found",
        "urn:smcp:problem:not-found",
      );
    return rows[0];
  }

  public async getCapsuleManifest(
    tenantSubject: string,
    id: string,
  ): Promise<{ capsule: CapsuleRecord; plan: CapsulePlanRecord }> {
    const capsule = await this.getCapsule(tenantSubject, id);
    const plan = await this.getCapsulePlan(tenantSubject, capsule.plan_id);
    return { capsule, plan };
  }

  public async createProject(
    tenantSubject: string,
    actorSubject: string,
    requestId: string,
    idempotencyKey: string,
    input: CreateProjectInput,
  ): Promise<{ project: ProjectRecord; created: boolean }> {
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();
    return this.sql.begin(async (transaction) => {
      const previous = await transaction<ProjectRecord[]>`
        SELECT id, tenant_subject, name, created_at
        FROM projects
        WHERE tenant_subject = ${tenantSubject} AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const matches = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM projects WHERE id = ${previous[0].id}
        `;
        if (!matches[0]?.matches)
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        return { project: previous[0], created: false };
      }
      const id = randomUUID();
      const rows = await transaction<ProjectRecord[]>`
        INSERT INTO projects (
          id, tenant_subject, name, idempotency_key, request_fingerprint
        ) VALUES (${id}, ${tenantSubject}, ${input.name}, ${idempotencyKey}, ${fingerprint})
        RETURNING id, tenant_subject, name, created_at
      `;
      await transaction`
        INSERT INTO project_quotas (tenant_subject, project_id)
        VALUES (${tenantSubject}, ${id})
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, action, resource_type,
          resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${id}, ${actorSubject}, 'project.created', 'project',
          ${id}, ${requestId}, 'success'
        )
      `;
      return { project: rows[0]!, created: true };
    });
  }

  public async createSourceObject(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    idempotencyKey: string,
    input: PresignUploadInput,
    objectKey: string,
    expiresAt: Date,
  ): Promise<{ source: SourceObjectRecord; created: boolean }> {
    await this.assertProject(tenantSubject, input.project_id);
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();
    return this.sql.begin(async (transaction) => {
      const previous = await transaction<SourceObjectRecord[]>`
        SELECT id, tenant_subject, project_id, object_key, declared_mime,
               expected_bytes, upload_expires_at
        FROM source_objects
        WHERE tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const matches = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM source_objects WHERE id = ${previous[0].id}
        `;
        if (!matches[0]?.matches)
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        return { source: previous[0], created: false };
      }
      await transaction`
        SELECT pg_advisory_xact_lock(
          hashtextextended(${`${tenantSubject}:${input.project_id}`}, 0)
        )
      `;
      const quota = await transaction<
        { max_monthly_input_bytes: number; used_bytes: number }[]
      >`
        SELECT q.max_monthly_input_bytes,
               COALESCE(u.value, 0) AS used_bytes
        FROM project_quotas q
        LEFT JOIN usage_counters u
          ON u.tenant_subject = q.tenant_subject
         AND u.project_id = q.project_id
         AND u.period_start = date_trunc('month', now())
         AND u.metric = 'input_bytes'
        WHERE q.tenant_subject = ${tenantSubject} AND q.project_id = ${input.project_id}
      `;
      if (
        !quota[0] ||
        Number(quota[0].used_bytes) + input.bytes >
          Number(quota[0].max_monthly_input_bytes)
      ) {
        throw new ApiProblem(
          429,
          "Project monthly input-byte quota exceeded",
          "urn:smcp:problem:quota-exceeded",
        );
      }
      const id = randomUUID();
      const rows = await transaction<SourceObjectRecord[]>`
        INSERT INTO source_objects (
          id, tenant_subject, project_id, object_key, declared_mime,
          expected_bytes, upload_expires_at, sha256,
          idempotency_key, request_fingerprint
        ) VALUES (
          ${id}, ${tenantSubject}, ${input.project_id}, ${objectKey}, ${input.content_type},
          ${input.bytes}, ${expiresAt},
          ${input.sha256 ? Buffer.from(input.sha256, "hex") : null},
          ${idempotencyKey}, ${fingerprint}
        )
        RETURNING id, tenant_subject, project_id, object_key, declared_mime,
                  expected_bytes, upload_expires_at
      `;
      await transaction`
        INSERT INTO usage_counters (
          tenant_subject, project_id, period_start, metric, value
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, date_trunc('month', now()),
          'input_bytes', ${input.bytes}
        )
        ON CONFLICT (tenant_subject, project_id, period_start, metric)
        DO UPDATE SET value = usage_counters.value + EXCLUDED.value
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, api_key_id, action,
          resource_type, resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, ${actorSubject}, ${apiKeyId},
          'upload.presigned', 'source_object', ${id}, ${requestId}, 'success'
        )
      `;
      return { source: rows[0]!, created: true };
    });
  }

  public async scheduleApiKeyRotation(
    tenantSubject: string,
    actorSubject: string,
    requestId: string,
    oldKeyId: string,
    newKeyId: string,
    revokeAt: Date,
  ): Promise<ApiKeyRotationRecord> {
    return this.sql.begin(async (transaction) => {
      const id = randomUUID();
      const rows = await transaction<ApiKeyRotationRecord[]>`
        INSERT INTO api_key_rotations (
          id, tenant_subject, old_key_id, new_key_id, revoke_at, created_by
        ) VALUES (
          ${id}, ${tenantSubject}, ${oldKeyId}, ${newKeyId}, ${revokeAt}, ${actorSubject}
        )
        RETURNING id, tenant_subject, old_key_id, new_key_id, revoke_at, attempt
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, actor_subject, api_key_id, action, resource_type,
          resource_id, request_id, outcome, metadata
        ) VALUES (
          ${tenantSubject}, ${actorSubject}, ${oldKeyId}, 'api_key.rotation_scheduled',
          'api_key', ${oldKeyId}, ${requestId}, 'success',
          ${transaction.json({ new_key_id: newKeyId, revoke_at: revokeAt.toISOString() })}
        )
      `;
      return rows[0]!;
    });
  }

  public async apiKeyRotationExists(
    tenantSubject: string,
    oldKeyId: string,
  ): Promise<boolean> {
    const rows = await this.sql<{ exists: boolean }[]>`
      SELECT EXISTS(
        SELECT 1 FROM api_key_rotations
        WHERE tenant_subject = ${tenantSubject} AND old_key_id = ${oldKeyId}
      ) AS exists
    `;
    return rows[0]?.exists ?? false;
  }

  public async markApiKeyRotationRevoked(id: string): Promise<void> {
    await this.sql`
      UPDATE api_key_rotations SET revoked_at = now(), claim_token = NULL, claimed_at = NULL
      WHERE id = ${id} AND revoked_at IS NULL
    `;
  }

  public async claimDueApiKeyRotations(
    claimToken: string,
    limit: number,
  ): Promise<ApiKeyRotationRecord[]> {
    return this.sql<ApiKeyRotationRecord[]>`
      UPDATE api_key_rotations
      SET claim_token = ${claimToken}, claimed_at = now(), attempt = attempt + 1
      WHERE id IN (
        SELECT id FROM api_key_rotations
        WHERE revoked_at IS NULL AND revoke_at <= now()
          AND (claimed_at IS NULL OR claimed_at < now() - interval '5 minutes')
        ORDER BY revoke_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT ${limit}
      )
      RETURNING id, tenant_subject, old_key_id, new_key_id, revoke_at, attempt
    `;
  }

  public async completeApiKeyRotation(
    id: string,
    claimToken: string,
  ): Promise<void> {
    await this.sql`
      UPDATE api_key_rotations
      SET revoked_at = now(), claim_token = NULL, claimed_at = NULL, last_error = NULL
      WHERE id = ${id} AND claim_token = ${claimToken} AND revoked_at IS NULL
    `;
  }

  public async retryApiKeyRotation(
    id: string,
    claimToken: string,
    errorCode: string,
  ): Promise<void> {
    await this.sql`
      UPDATE api_key_rotations
      SET claim_token = NULL, claimed_at = NULL, last_error = ${errorCode},
          revoke_at = now() + power(2, LEAST(attempt, 10)) * interval '1 second'
      WHERE id = ${id} AND claim_token = ${claimToken} AND revoked_at IS NULL
    `;
  }

  public async createCompressionJob(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    idempotencyKey: string,
    input: CreateCompressionInput,
  ): Promise<{ job: CompressionJobRecord; created: boolean }> {
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();

    return this.sql.begin(async (transaction) => {
      const previous = await transaction<CompressionJobRecord[]>`
        SELECT id, tenant_subject, project_id, input_type, profile, target_bytes,
               status, source_object_id, selected_candidate_id, requested_at,
               completed_at, error_code
        FROM compression_jobs
        WHERE tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const hashes = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM compression_jobs
          WHERE id = ${previous[0].id} AND tenant_subject = ${tenantSubject}
        `;
        if (!hashes[0]?.matches) {
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        }
        return { job: previous[0], created: false };
      }

      const source = await transaction<{ id: string }[]>`
        SELECT id FROM source_objects
        WHERE id = ${input.source_object_id}
          AND project_id = ${input.project_id}
          AND tenant_subject = ${tenantSubject}
      `;
      if (!source[0]) {
        throw new ApiProblem(
          404,
          "Source object not found",
          "urn:smcp:problem:not-found",
        );
      }

      await transaction`
        SELECT pg_advisory_xact_lock(
          hashtextextended(${`${tenantSubject}:${input.project_id}`}, 0)
        )
      `;
      const quota = await transaction<
        {
          max_monthly_jobs: number;
          max_concurrent_jobs: number;
          used_jobs: number;
          active_jobs: number;
        }[]
      >`
        SELECT q.max_monthly_jobs, q.max_concurrent_jobs,
               COALESCE(u.value, 0) AS used_jobs,
               (SELECT count(*) FROM compression_jobs active
                WHERE active.tenant_subject = q.tenant_subject
                  AND active.project_id = q.project_id
                  AND active.status NOT IN ('COMPLETED', 'FAILED_TERMINAL', 'CANCELLED')) AS active_jobs
        FROM project_quotas q
        LEFT JOIN usage_counters u
          ON u.tenant_subject = q.tenant_subject
         AND u.project_id = q.project_id
         AND u.period_start = date_trunc('month', now())
         AND u.metric = 'compression_jobs'
        WHERE q.tenant_subject = ${tenantSubject} AND q.project_id = ${input.project_id}
      `;
      if (
        !quota[0] ||
        Number(quota[0].used_jobs) >= Number(quota[0].max_monthly_jobs)
      )
        throw new ApiProblem(
          429,
          "Project monthly compression-job quota exceeded",
          "urn:smcp:problem:quota-exceeded",
        );
      if (Number(quota[0].active_jobs) >= Number(quota[0].max_concurrent_jobs))
        throw new ApiProblem(
          429,
          "Project concurrent compression-job quota exceeded",
          "urn:smcp:problem:quota-exceeded",
        );

      const id = randomUUID();
      const rows = await transaction<CompressionJobRecord[]>`
        INSERT INTO compression_jobs (
          id, tenant_subject, project_id, input_type, profile, target_bytes,
          source_object_id, idempotency_key, request_fingerprint
        ) VALUES (
          ${id}, ${tenantSubject}, ${input.project_id}, ${input.input_type}, ${input.profile},
          ${input.target_bytes ?? null}, ${input.source_object_id}, ${idempotencyKey}, ${fingerprint}
        )
        RETURNING id, tenant_subject, project_id, input_type, profile, target_bytes,
                  status, source_object_id, selected_candidate_id, requested_at,
                  completed_at, error_code
      `;
      await transaction`
        INSERT INTO usage_counters (
          tenant_subject, project_id, period_start, metric, value
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, date_trunc('month', now()),
          'compression_jobs', 1
        )
        ON CONFLICT (tenant_subject, project_id, period_start, metric)
        DO UPDATE SET value = usage_counters.value + 1
      `;
      await transaction`
        INSERT INTO outbox_events (
          tenant_subject, project_id, topic, aggregate_id, payload
        )
        VALUES (
          ${tenantSubject}, ${input.project_id}, 'compression.requested', ${id},
          ${transaction.json({ job_id: id, tenant_subject: tenantSubject })}
        )
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, api_key_id, action,
          resource_type, resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, ${actorSubject}, ${apiKeyId},
          'compression.created', 'compression_job', ${id}, ${requestId}, 'success'
        )
      `;
      return { job: rows[0]!, created: true };
    });
  }

  public async getCompressionJob(
    tenantSubject: string,
    id: string,
  ): Promise<CompressionJobRecord> {
    const rows = await this.sql<CompressionJobRecord[]>`
      SELECT id, tenant_subject, project_id, input_type, profile, target_bytes,
             status, source_object_id, selected_candidate_id, requested_at,
             completed_at, error_code
      FROM compression_jobs
      WHERE tenant_subject = ${tenantSubject} AND id = ${id}
    `;
    if (!rows[0])
      throw new ApiProblem(
        404,
        "Compression job not found",
        "urn:smcp:problem:not-found",
      );
    return rows[0];
  }

  public async listCandidates(
    tenantSubject: string,
    jobId: string,
  ): Promise<CandidateRecord[]> {
    await this.getCompressionJob(tenantSubject, jobId);
    return this.sql<CandidateRecord[]>`
      SELECT id, codec_id, codec_version, payload_bytes, container_overhead_bytes,
             quality_metrics, quality_gate_passed, determinism_status
      FROM encoding_candidates
      WHERE tenant_subject = ${tenantSubject} AND job_id = ${jobId}
      ORDER BY payload_bytes ASC, codec_id ASC, id ASC
    `;
  }

  public async getArtifact(
    tenantSubject: string,
    id: string,
  ): Promise<ArtifactRecord> {
    const rows = await this.sql<ArtifactRecord[]>`
      SELECT a.id, a.tenant_subject, j.project_id, a.job_id, a.candidate_id,
             a.kind, a.object_key, a.bytes, encode(a.sha256, 'hex') AS sha256_hex
      FROM artifacts a
      JOIN compression_jobs j
        ON j.id = a.job_id AND j.tenant_subject = a.tenant_subject
      WHERE a.tenant_subject = ${tenantSubject} AND a.id = ${id}
    `;
    if (!rows[0])
      throw new ApiProblem(
        404,
        "Artifact not found",
        "urn:smcp:problem:not-found",
      );
    return rows[0];
  }

  public async createDecompressionJob(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    idempotencyKey: string,
    input: CreateDecompressionInput,
  ): Promise<{ job: DecompressionJobRecord; created: boolean }> {
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();
    return this.sql.begin(async (transaction) => {
      const previous = await transaction<DecompressionJobRecord[]>`
        SELECT id, tenant_subject, project_id, artifact_id, status, output_object_key,
               output_bytes, CASE WHEN output_sha256 IS NULL THEN NULL
                 ELSE encode(output_sha256, 'hex') END AS output_sha256_hex,
               verified, error_code, requested_at, completed_at
        FROM decompression_jobs
        WHERE tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const matches = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM decompression_jobs WHERE id = ${previous[0].id}
        `;
        if (!matches[0]?.matches) {
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        }
        return { job: previous[0], created: false };
      }

      const artifacts = await transaction<{ id: string }[]>`
        SELECT a.id FROM artifacts a
        JOIN compression_jobs j
          ON j.id = a.job_id AND j.tenant_subject = a.tenant_subject
        WHERE a.id = ${input.artifact_id} AND a.tenant_subject = ${tenantSubject}
          AND j.project_id = ${input.project_id} AND a.kind = 'compressed'
      `;
      if (!artifacts[0])
        throw new ApiProblem(
          404,
          "Artifact not found",
          "urn:smcp:problem:not-found",
        );

      const id = randomUUID();
      const rows = await transaction<DecompressionJobRecord[]>`
        INSERT INTO decompression_jobs (
          id, tenant_subject, project_id, artifact_id, idempotency_key, request_fingerprint
        ) VALUES (
          ${id}, ${tenantSubject}, ${input.project_id}, ${input.artifact_id},
          ${idempotencyKey}, ${fingerprint}
        )
        RETURNING id, tenant_subject, project_id, artifact_id, status,
          output_object_key, output_bytes, NULL::text AS output_sha256_hex,
          verified, error_code, requested_at, completed_at
      `;
      await transaction`
        INSERT INTO outbox_events (
          tenant_subject, project_id, topic, aggregate_id, payload
        )
        VALUES (
          ${tenantSubject}, ${input.project_id}, 'decompression.requested', ${id},
          ${transaction.json({ decompression_id: id, tenant_subject: tenantSubject })}
        )
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, api_key_id, action,
          resource_type, resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, ${actorSubject}, ${apiKeyId},
          'decompression.created', 'decompression_job', ${id}, ${requestId}, 'success'
        )
      `;
      return { job: rows[0]!, created: true };
    });
  }

  public async getDecompressionJob(
    tenantSubject: string,
    id: string,
  ): Promise<DecompressionJobRecord> {
    const rows = await this.sql<DecompressionJobRecord[]>`
      SELECT id, tenant_subject, project_id, artifact_id, status, output_object_key,
             output_bytes, CASE WHEN output_sha256 IS NULL THEN NULL
               ELSE encode(output_sha256, 'hex') END AS output_sha256_hex,
             verified, error_code, requested_at, completed_at
      FROM decompression_jobs
      WHERE tenant_subject = ${tenantSubject} AND id = ${id}
    `;
    if (!rows[0])
      throw new ApiProblem(
        404,
        "Decompression job not found",
        "urn:smcp:problem:not-found",
      );
    return rows[0];
  }

  public async getProjectUsage(
    tenantSubject: string,
    projectId: string,
  ): Promise<ProjectUsageRecord> {
    const rows = await this.sql<
      {
        period_start: Date;
        counters: Record<string, number>;
        active_jobs: number;
        max_monthly_input_bytes: number;
        max_monthly_jobs: number;
        max_concurrent_jobs: number;
        max_monthly_capsules: number;
      }[]
    >`
      SELECT date_trunc('month', now()) AS period_start,
             COALESCE(
               (SELECT jsonb_object_agg(metric, value)
                FROM usage_counters u
                WHERE u.tenant_subject = q.tenant_subject
                  AND u.project_id = q.project_id
                  AND u.period_start = date_trunc('month', now())),
               '{}'::jsonb
             ) AS counters,
             (SELECT count(*) FROM compression_jobs active
              WHERE active.tenant_subject = q.tenant_subject
                AND active.project_id = q.project_id
                AND active.status NOT IN ('COMPLETED', 'FAILED_TERMINAL', 'CANCELLED')) AS active_jobs,
             q.max_monthly_input_bytes, q.max_monthly_jobs,
             q.max_concurrent_jobs, q.max_monthly_capsules
      FROM project_quotas q
      WHERE q.tenant_subject = ${tenantSubject} AND q.project_id = ${projectId}
    `;
    const row = rows[0];
    if (!row)
      throw new ApiProblem(
        404,
        "Project not found",
        "urn:smcp:problem:not-found",
      );
    return {
      project_id: projectId,
      period_start: row.period_start,
      counters: row.counters,
      active_jobs: Number(row.active_jobs),
      quotas: {
        max_monthly_input_bytes: Number(row.max_monthly_input_bytes),
        max_monthly_jobs: Number(row.max_monthly_jobs),
        max_concurrent_jobs: Number(row.max_concurrent_jobs),
        max_monthly_capsules: Number(row.max_monthly_capsules),
      },
    };
  }

  public async createWebhookEndpoint(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    idempotencyKey: string,
    input: CreateWebhookEndpointInput,
    secretCiphertext: Buffer,
  ): Promise<{ endpoint: WebhookEndpointRecord; created: boolean }> {
    await this.assertProject(tenantSubject, input.project_id);
    const fingerprint = createHash("sha256")
      .update(JSON.stringify(input))
      .digest();
    return this.sql.begin(async (transaction) => {
      const previous = await transaction<WebhookEndpointRecord[]>`
        SELECT id, tenant_subject, project_id, url, event_types, enabled,
               created_at, disabled_at
        FROM webhook_endpoints
        WHERE tenant_subject = ${tenantSubject}
          AND project_id = ${input.project_id}
          AND idempotency_key = ${idempotencyKey}
        FOR UPDATE
      `;
      if (previous[0]) {
        const matches = await transaction<{ matches: boolean }[]>`
          SELECT request_fingerprint = ${fingerprint} AS matches
          FROM webhook_endpoints WHERE id = ${previous[0].id}
        `;
        if (!matches[0]?.matches)
          throw new ApiProblem(
            409,
            "Idempotency key reused with different input",
            "urn:smcp:problem:idempotency-conflict",
          );
        return { endpoint: previous[0], created: false };
      }
      const id = randomUUID();
      const rows = await transaction<WebhookEndpointRecord[]>`
        INSERT INTO webhook_endpoints (
          id, tenant_subject, project_id, url, secret_ciphertext, event_types,
          idempotency_key, request_fingerprint
        ) VALUES (
          ${id}, ${tenantSubject}, ${input.project_id}, ${input.url},
          ${secretCiphertext}, ${input.event_types}, ${idempotencyKey}, ${fingerprint}
        )
        RETURNING id, tenant_subject, project_id, url, event_types, enabled,
                  created_at, disabled_at
      `;
      await transaction`
        INSERT INTO audit_events (
          tenant_subject, project_id, actor_subject, api_key_id, action,
          resource_type, resource_id, request_id, outcome
        ) VALUES (
          ${tenantSubject}, ${input.project_id}, ${actorSubject}, ${apiKeyId},
          'webhook.created', 'webhook_endpoint', ${id}, ${requestId}, 'success'
        )
      `;
      return { endpoint: rows[0]!, created: true };
    });
  }

  public async listWebhookEndpoints(
    tenantSubject: string,
    projectId: string,
  ): Promise<WebhookEndpointRecord[]> {
    await this.assertProject(tenantSubject, projectId);
    return this.sql<WebhookEndpointRecord[]>`
      SELECT id, tenant_subject, project_id, url, event_types, enabled,
             created_at, disabled_at
      FROM webhook_endpoints
      WHERE tenant_subject = ${tenantSubject} AND project_id = ${projectId}
      ORDER BY created_at, id
    `;
  }

  public async disableWebhookEndpoint(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    id: string,
  ): Promise<void> {
    const rows = await this.sql<{ project_id: string }[]>`
      UPDATE webhook_endpoints
      SET enabled = false, disabled_at = COALESCE(disabled_at, now())
      WHERE tenant_subject = ${tenantSubject} AND id = ${id}
      RETURNING project_id
    `;
    if (!rows[0])
      throw new ApiProblem(
        404,
        "Webhook not found",
        "urn:smcp:problem:not-found",
      );
    await this.audit(
      tenantSubject,
      rows[0].project_id,
      actorSubject,
      apiKeyId,
      "webhook.disabled",
      "webhook_endpoint",
      id,
      requestId,
      "success",
    );
  }

  public async materializeWebhookDeliveries(): Promise<void> {
    await this.sql.begin(async (transaction) => {
      await transaction`
        INSERT INTO webhook_deliveries (
          tenant_subject, endpoint_id, event_id, attempt, status,
          next_attempt_at, event_type, payload
        )
        SELECT o.tenant_subject, e.id, o.id, 0, 'PENDING', now(), o.topic,
               jsonb_build_object(
                 'id', o.id, 'type', o.topic, 'created_at', o.created_at,
                 'data', o.payload
               )
        FROM outbox_events o
        JOIN webhook_endpoints e
          ON e.tenant_subject = o.tenant_subject
         AND e.project_id = o.project_id
         AND e.enabled = true
         AND o.topic = ANY(e.event_types)
        WHERE o.published_at IS NULL AND o.project_id IS NOT NULL
        ON CONFLICT (endpoint_id, event_id) DO NOTHING
      `;
      await transaction`
        UPDATE outbox_events SET published_at = now()
        WHERE published_at IS NULL AND project_id IS NOT NULL
      `;
    });
  }

  public async claimWebhookDeliveries(
    claimToken: string,
    limit: number,
  ): Promise<WebhookDeliveryClaim[]> {
    return this.sql<WebhookDeliveryClaim[]>`
      UPDATE webhook_deliveries d
      SET claim_token = ${claimToken}, claimed_at = now(), attempt = d.attempt + 1
      FROM webhook_endpoints e
      WHERE d.id IN (
        SELECT pending.id FROM webhook_deliveries pending
        JOIN webhook_endpoints endpoint
          ON endpoint.id = pending.endpoint_id
         AND endpoint.tenant_subject = pending.tenant_subject
        WHERE pending.status IN ('PENDING', 'RETRY')
          AND pending.next_attempt_at <= now()
          AND endpoint.enabled = true
          AND (pending.claimed_at IS NULL OR pending.claimed_at < now() - interval '2 minutes')
        ORDER BY pending.next_attempt_at, pending.id
        FOR UPDATE OF pending SKIP LOCKED
        LIMIT ${limit}
      )
        AND e.id = d.endpoint_id AND e.tenant_subject = d.tenant_subject
      RETURNING d.id, d.tenant_subject, d.endpoint_id, d.event_id,
                d.event_type, d.payload, d.attempt, e.url, e.secret_ciphertext
    `;
  }

  public async completeWebhookDelivery(
    id: string,
    claimToken: string,
    responseCode: number,
  ): Promise<void> {
    await this.sql`
      UPDATE webhook_deliveries
      SET status = 'DELIVERED', response_code = ${responseCode},
          delivered_at = now(), next_attempt_at = NULL,
          claim_token = NULL, claimed_at = NULL, last_error = NULL
      WHERE id = ${id} AND claim_token = ${claimToken}
    `;
  }

  public async failWebhookDelivery(
    id: string,
    claimToken: string,
    attempt: number,
    maximumAttempts: number,
    errorCode: string,
    responseCode: number | null,
  ): Promise<void> {
    const terminal = attempt >= maximumAttempts;
    await this.sql`
      UPDATE webhook_deliveries
      SET status = ${terminal ? "DEAD_LETTER" : "RETRY"},
          response_code = ${responseCode}, last_error = ${errorCode},
          next_attempt_at = ${terminal ? null : this.sql`now() + power(2, LEAST(${attempt}, 10)) * interval '1 second'`},
          claim_token = NULL, claimed_at = NULL
      WHERE id = ${id} AND claim_token = ${claimToken}
    `;
  }

  public async cancelCompressionJob(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    id: string,
  ): Promise<CompressionJobRecord> {
    const rows = await this.sql<CompressionJobRecord[]>`
      UPDATE compression_jobs
      SET status = 'CANCELLED', completed_at = now()
      WHERE tenant_subject = ${tenantSubject} AND id = ${id}
        AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL', 'CANCELLED')
      RETURNING id, tenant_subject, project_id, input_type, profile, target_bytes,
                status, source_object_id, selected_candidate_id, requested_at,
                completed_at, error_code
    `;
    if (!rows[0]) {
      throw new ApiProblem(
        409,
        "Compression job is already terminal or absent",
        "urn:smcp:problem:invalid-state",
      );
    }
    await this.audit(
      tenantSubject,
      rows[0].project_id,
      actorSubject,
      apiKeyId,
      "compression.cancelled",
      "compression_job",
      id,
      requestId,
      "success",
    );
    return rows[0];
  }

  private async assertProject(
    tenantSubject: string,
    projectId: string,
  ): Promise<void> {
    const rows = await this.sql<{ exists: boolean }[]>`
      SELECT EXISTS(
        SELECT 1 FROM projects WHERE tenant_subject = ${tenantSubject} AND id = ${projectId}
      ) AS exists
    `;
    if (!rows[0]?.exists)
      throw new ApiProblem(
        404,
        "Project not found",
        "urn:smcp:problem:not-found",
      );
  }

  private async audit(
    tenantSubject: string,
    projectId: string | null,
    actorSubject: string,
    apiKeyId: string | null,
    action: string,
    resourceType: string,
    resourceId: string,
    requestId: string,
    outcome: string,
  ): Promise<void> {
    await this.sql`
      INSERT INTO audit_events (
        tenant_subject, project_id, actor_subject, api_key_id, action,
        resource_type, resource_id, request_id, outcome
      ) VALUES (
        ${tenantSubject}, ${projectId}, ${actorSubject}, ${apiKeyId}, ${action},
        ${resourceType}, ${resourceId}, ${requestId}, ${outcome}
      )
    `;
  }
}
