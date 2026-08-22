import { createHash, randomUUID } from "node:crypto";

import type {
  ContentType,
  CreateCompressionInput,
  CreateDecompressionInput,
  CreateProjectInput,
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

  public async createProject(
    tenantSubject: string,
    actorSubject: string,
    requestId: string,
    input: CreateProjectInput,
  ): Promise<ProjectRecord> {
    const id = randomUUID();
    const rows = await this.sql<ProjectRecord[]>`
      INSERT INTO projects (id, tenant_subject, name)
      VALUES (${id}, ${tenantSubject}, ${input.name})
      RETURNING id, tenant_subject, name, created_at
    `;
    await this.audit(
      tenantSubject,
      id,
      actorSubject,
      null,
      "project.created",
      "project",
      id,
      requestId,
      "success",
    );
    return rows[0]!;
  }

  public async createSourceObject(
    tenantSubject: string,
    actorSubject: string,
    apiKeyId: string,
    requestId: string,
    input: PresignUploadInput,
    objectKey: string,
    expiresAt: Date,
  ): Promise<SourceObjectRecord> {
    await this.assertProject(tenantSubject, input.project_id);
    const id = randomUUID();
    const rows = await this.sql<SourceObjectRecord[]>`
      INSERT INTO source_objects (
        id, tenant_subject, project_id, object_key, declared_mime,
        expected_bytes, upload_expires_at, sha256
      ) VALUES (
        ${id}, ${tenantSubject}, ${input.project_id}, ${objectKey}, ${input.content_type},
        ${input.bytes}, ${expiresAt}, ${input.sha256 ? Buffer.from(input.sha256, "hex") : null}
      )
      RETURNING id, tenant_subject, project_id, object_key, declared_mime,
                expected_bytes, upload_expires_at
    `;
    await this.audit(
      tenantSubject,
      input.project_id,
      actorSubject,
      apiKeyId,
      "upload.presigned",
      "source_object",
      id,
      requestId,
      "success",
    );
    return rows[0]!;
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
        INSERT INTO outbox_events (tenant_subject, topic, aggregate_id, payload)
        VALUES (
          ${tenantSubject}, 'compression.requested', ${id},
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
        INSERT INTO outbox_events (tenant_subject, topic, aggregate_id, payload)
        VALUES (
          ${tenantSubject}, 'decompression.requested', ${id},
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
