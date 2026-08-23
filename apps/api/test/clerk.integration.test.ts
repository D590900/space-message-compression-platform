import { afterEach, describe, expect, it } from "vitest";

import {
  ProductionClerkGateway,
  requireApiKey,
  type ManagedApiKey,
} from "../src/auth.js";
import { loadConfig } from "../src/config.js";

const integrationEnabled = process.env.CLERK_INTEGRATION === "1";

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value)
    throw new Error(`${name} is required for the Clerk integration suite`);
  return value;
}

async function waitForRevocation(
  clerk: ProductionClerkGateway,
  secret: string,
): Promise<unknown> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const result = await requireApiKey(clerk, `Bearer ${secret}`, "jobs:read")
      .then(() => undefined)
      .catch((error: unknown) => error);
    if (result) return result;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    "Clerk API-key revocation did not propagate within 30 seconds",
  );
}

describe.runIf(integrationEnabled)("real Clerk API-key lifecycle", () => {
  let clerk: ProductionClerkGateway | undefined;
  let createdKey: ManagedApiKey | undefined;

  function createGateway(): ProductionClerkGateway {
    return new ProductionClerkGateway(
      loadConfig({
        NODE_ENV: "test",
        LOG_LEVEL: "silent",
        DATABASE_URL: "postgresql://test:test@localhost:5432/test",
        VALKEY_URL: "redis://localhost:6379/0",
        CLERK_SECRET_KEY: requiredEnvironment("CLERK_SECRET_KEY"),
        CLERK_PUBLISHABLE_KEY: requiredEnvironment("CLERK_PUBLISHABLE_KEY"),
        WEB_ORIGIN: "http://localhost:3000",
        API_ORIGIN: "http://localhost:3001",
        S3_ENDPOINT: "http://localhost:9000",
        S3_REGION: "us-east-1",
        S3_BUCKET: "test-bucket",
        S3_ACCESS_KEY_ID: "test",
        S3_SECRET_ACCESS_KEY: "test",
        S3_FORCE_PATH_STYLE: "true",
        IDENTIFIER_HMAC_SECRET: "test-identifier-hmac-secret-32-bytes",
        WEBHOOK_SECRET_ENCRYPTION_KEY:
          "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=",
      }),
    );
  }

  afterEach(async () => {
    if (clerk && createdKey && !createdKey.revoked) {
      await clerk.revokeApiKey(createdKey.id, "Protected CI cleanup");
    }
    clerk = undefined;
    createdKey = undefined;
  });

  it("accepts a scoped service key and rejects it after revocation", async () => {
    clerk = createGateway();
    createdKey = await clerk.createApiKey({
      name: `smcp-protected-ci-${Date.now()}`,
      subject: requiredEnvironment("CLERK_TEST_ORG_ID"),
      createdBy: requiredEnvironment("CLERK_TEST_USER_ID"),
      scopes: ["jobs:read"],
      claims: { smcp_issued: true, smcp_protected_ci: true },
      secondsUntilExpiration: 600,
    });
    expect(createdKey.secret).toBeTruthy();

    const secret = createdKey.secret!;
    await expect(
      requireApiKey(clerk, `Bearer ${secret}`, "jobs:read"),
    ).resolves.toMatchObject({
      tenantSubject: requiredEnvironment("CLERK_TEST_ORG_ID"),
      keyId: createdKey.id,
      scopes: ["jobs:read"],
    });
    await expect(
      requireApiKey(clerk, `Bearer ${secret}`, "jobs:create"),
    ).rejects.toMatchObject({
      status: 403,
      type: "urn:smcp:problem:insufficient-scope",
    });

    await clerk.revokeApiKey(createdKey.id, "Protected CI revocation test");
    createdKey = { ...createdKey, revoked: true };
    await expect(waitForRevocation(clerk, secret)).resolves.toMatchObject({
      status: 401,
      type: "urn:smcp:problem:invalid-api-key",
    });
  }, 45_000);
});
