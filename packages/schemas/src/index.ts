import { z } from "zod";

export const uuidSchema = z.uuid();
export const sha256HexSchema = z.string().regex(/^[a-f0-9]{64}$/);

export const scopeValues = [
  "jobs:create",
  "jobs:read",
  "jobs:cancel",
  "artifacts:read",
  "decompressions:create",
  "capsules:plan",
  "capsules:create",
  "capsules:read",
  "codecs:read",
  "webhooks:manage",
  "admin:benchmarks",
  "admin:codecs",
] as const;

export const apiScopeSchema = z.enum(scopeValues);
export type ApiScope = z.infer<typeof apiScopeSchema>;

export const profileSchema = z.enum(["faithful", "ultra", "semantic"]);
export type Profile = z.infer<typeof profileSchema>;

export const contentTypeSchema = z.enum(["TEXT", "IMAGE", "AUDIO", "VIDEO"]);
export type ContentType = z.infer<typeof contentTypeSchema>;

export const jobStatusValues = [
  "PENDING",
  "VALIDATING",
  "PREPROCESSING",
  "ENCODING",
  "MEASURING",
  "SELECTING",
  "PACKAGING",
  "COMPLETED",
  "FAILED_RETRYABLE",
  "FAILED_TERMINAL",
  "CANCELLED",
] as const;

export const jobStatusSchema = z.enum(jobStatusValues);
export type JobStatus = z.infer<typeof jobStatusSchema>;

export const createProjectSchema = z.strictObject({
  name: z.string().trim().min(1).max(120),
});

export const createApiKeySchema = z.strictObject({
  name: z.string().trim().min(1).max(100),
  scopes: z.array(apiScopeSchema).min(1).max(scopeValues.length),
  expires_at: z.iso.datetime({ offset: true }),
});

export const rotateApiKeySchema = z.strictObject({
  overlap_seconds: z.int().min(0).max(86_400).default(0),
});

export const allowedMimeTypes = [
  "text/plain",
  "image/avif",
  "image/jpeg",
  "image/png",
  "audio/ogg",
  "audio/wav",
  "video/mp4",
  "video/webm",
] as const;

export const presignUploadSchema = z.strictObject({
  project_id: uuidSchema,
  filename: z.string().trim().min(1).max(255),
  content_type: z.enum(allowedMimeTypes),
  bytes: z.int().positive().max(1_073_741_824),
  sha256: sha256HexSchema.optional(),
});

export const createCompressionSchema = z.strictObject({
  project_id: uuidSchema,
  source_object_id: uuidSchema,
  input_type: contentTypeSchema,
  profile: profileSchema,
  target_bytes: z.int().positive().optional(),
});

export const resourceIdParamsSchema = z.strictObject({ id: uuidSchema });

export const idempotencyKeySchema = z
  .string()
  .min(8)
  .max(200)
  .regex(/^[\x21-\x7e]+$/);

export const problemSchema = z.object({
  type: z.string(),
  title: z.string(),
  status: z.int().min(400).max(599),
  detail: z.string().optional(),
  instance: z.string().optional(),
  request_id: z.string(),
});

export type CreateProjectInput = z.infer<typeof createProjectSchema>;
export type CreateApiKeyInput = z.infer<typeof createApiKeySchema>;
export type PresignUploadInput = z.infer<typeof presignUploadSchema>;
export type CreateCompressionInput = z.infer<typeof createCompressionSchema>;
