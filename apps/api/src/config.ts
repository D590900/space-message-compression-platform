import { z } from "zod";

const booleanString = z
  .enum(["true", "false"])
  .transform((value) => value === "true");

const optionalUrl = z.preprocess(
  (value) => (value === "" ? undefined : value),
  z.url().optional(),
);

const configSchema = z
  .object({
    NODE_ENV: z
      .enum(["development", "test", "production"])
      .default("development"),
    HOST: z.string().default("0.0.0.0"),
    PORT: z.coerce.number().int().min(1).max(65_535).default(3001),
    LOG_LEVEL: z
      .enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"])
      .default("info"),
    DATABASE_URL: z.url(),
    VALKEY_URL: z.url(),
    CLERK_SECRET_KEY: z.string().min(1),
    CLERK_PUBLISHABLE_KEY: z.string().min(1),
    WEB_ORIGIN: z.url(),
    API_ORIGIN: z.url(),
    S3_ENDPOINT: z.url(),
    S3_PUBLIC_ENDPOINT: z.url().optional(),
    S3_REGION: z.string().min(1).default("us-east-1"),
    S3_BUCKET: z.string().min(3),
    S3_ACCESS_KEY_ID: z.string().min(1),
    S3_SECRET_ACCESS_KEY: z.string().min(1),
    S3_FORCE_PATH_STYLE: booleanString.default(true),
    SIGNED_URL_TTL_SECONDS: z.coerce
      .number()
      .int()
      .min(30)
      .max(900)
      .default(300),
    MAX_UPLOAD_BYTES: z.coerce.number().int().positive().default(1_073_741_824),
    TENANT_RATE_COST_PER_MINUTE: z.coerce
      .number()
      .int()
      .positive()
      .default(1_000),
    CREDENTIAL_ROUTE_COST_PER_MINUTE: z.coerce
      .number()
      .int()
      .positive()
      .default(120),
    IDENTIFIER_HMAC_SECRET: z.string().min(32),
    CAPSULE_CLI_PATH: z.string().min(1).default("smcp-capsule"),
    KEY_ROTATION_POLL_MS: z.coerce
      .number()
      .int()
      .min(100)
      .max(60_000)
      .default(5_000),
    JOB_OUTBOX_POLL_MS: z.coerce
      .number()
      .int()
      .min(100)
      .max(60_000)
      .default(250),
    WEBHOOK_SECRET_ENCRYPTION_KEY: z.string().refine((value) => {
      try {
        return Buffer.from(value, "base64").length === 32;
      } catch {
        return false;
      }
    }, "must be a Base64-encoded 32-byte key"),
    WEBHOOK_POLL_MS: z.coerce
      .number()
      .int()
      .min(100)
      .max(60_000)
      .default(1_000),
    WEBHOOK_MAX_ATTEMPTS: z.coerce.number().int().min(1).max(20).default(8),
    WEBHOOK_TIMEOUT_MS: z.coerce
      .number()
      .int()
      .min(100)
      .max(30_000)
      .default(10_000),
    METRICS_BEARER_TOKEN: z.string().min(32).optional(),
    OTEL_SERVICE_NAME: z.string().min(1).default("smcp-api"),
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: optionalUrl,
  })
  .superRefine((value, context) => {
    if (value.NODE_ENV === "production" && !value.METRICS_BEARER_TOKEN) {
      context.addIssue({
        code: "custom",
        path: ["METRICS_BEARER_TOKEN"],
        message: "is required in production",
      });
    }
  });

export type ApiConfig = z.infer<typeof configSchema>;

export function loadConfig(
  environment: NodeJS.ProcessEnv = process.env,
): ApiConfig {
  return configSchema.parse(environment);
}
