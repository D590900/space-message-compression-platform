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

export const webhookEventTypeValues = [
  "compression.completed",
  "decompression.completed",
  "capsule.completed",
] as const;
export const webhookEventTypeSchema = z.enum(webhookEventTypeValues);

export const createWebhookEndpointSchema = z.strictObject({
  project_id: uuidSchema,
  url: z.url({ protocol: /^https$/, hostname: z.regexes.domain }),
  event_types: z
    .array(webhookEventTypeSchema)
    .min(1)
    .max(webhookEventTypeValues.length)
    .transform((values) => [...new Set(values)].sort()),
});
export const projectIdQuerySchema = z.strictObject({ project_id: uuidSchema });

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

export const createDecompressionSchema = z.strictObject({
  project_id: uuidSchema,
  artifact_id: uuidSchema,
});

export const createCapsulePlanSchema = z
  .strictObject({
    project_id: uuidSchema,
    budget_bytes: z.int().positive().max(1_073_741_824).default(2_000_000),
    ecc_percent: z.int().min(0).max(50).default(0),
    items: z
      .array(
        z.strictObject({
          job_id: uuidSchema,
          required: z.boolean(),
          utility: z.int().min(0).max(1_000_000),
        }),
      )
      .min(1)
      .max(10_000),
  })
  .superRefine((input, context) => {
    const ids = new Set<string>();
    input.items.forEach((item, index) => {
      if (ids.has(item.job_id)) {
        context.addIssue({
          code: "custom",
          path: ["items", index, "job_id"],
          message: "job_id values must be unique",
        });
      }
      ids.add(item.job_id);
    });
  });

export const createCapsuleSchema = z.strictObject({
  project_id: uuidSchema,
  plan_id: uuidSchema,
  pad_to_budget: z.boolean().default(false),
});

export const verifyCapsuleSchema = z.strictObject({
  project_id: uuidSchema,
  capsule_id: uuidSchema,
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
export type CreateDecompressionInput = z.infer<
  typeof createDecompressionSchema
>;
export type CreateCapsulePlanInput = z.infer<typeof createCapsulePlanSchema>;
export type CreateCapsuleInput = z.infer<typeof createCapsuleSchema>;
export type VerifyCapsuleInput = z.infer<typeof verifyCapsuleSchema>;
export type CreateWebhookEndpointInput = z.infer<
  typeof createWebhookEndpointSchema
>;
export type WebhookEventType = z.infer<typeof webhookEventTypeSchema>;
