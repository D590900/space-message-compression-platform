import { createHash, randomUUID } from "node:crypto";

import type {
  ContentType,
  CreateCompressionInput,
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
