import { describe, expect, it } from "vitest";

import {
  type ClerkGateway,
  type ManagedApiKey,
  requireApiKey,
} from "../src/auth.js";

function managedKey(overrides: Partial<ManagedApiKey> = {}): ManagedApiKey {
  return {
    id: "apikey_test",
    name: "test",
    subject: "org_test",
    scopes: ["jobs:create"],
    claims: { smcp_issued: true },
    createdBy: "user_test",
    description: null,
    expiration: Date.now() + 60_000,
    expired: false,
    revoked: false,
    ...overrides,
  };
}

class FakeClerk implements ClerkGateway {
  public constructor(private readonly key: ManagedApiKey) {}
  public verifyApiKey(): Promise<ManagedApiKey> {
    return Promise.resolve(this.key);
  }
  public authenticateSession(): Promise<null> {
    return Promise.resolve(null);
  }
  public createApiKey(): Promise<ManagedApiKey> {
    return Promise.resolve(this.key);
  }
  public listApiKeys(): Promise<{ data: ManagedApiKey[]; totalCount: number }> {
    return Promise.resolve({ data: [this.key], totalCount: 1 });
  }
  public getApiKey(): Promise<ManagedApiKey> {
    return Promise.resolve(this.key);
  }
  public getApiKeySecret(): Promise<string> {
    return Promise.resolve("test-secret");
  }
  public revokeApiKey(): Promise<void> {
    return Promise.resolve();
  }
}

describe("API-key policy", () => {
  it("accepts a service-issued organization key with the required scope", async () => {
    const principal = await requireApiKey(
      new FakeClerk(managedKey()),
      "Bearer secret-value",
      "jobs:create",
    );
    expect(principal.tenantSubject).toBe("org_test");
    expect(principal.keyId).toBe("apikey_test");
  });

  it("rejects a key created outside the service", async () => {
    await expect(
      requireApiKey(
        new FakeClerk(managedKey({ claims: null })),
        "Bearer secret-value",
        "jobs:create",
      ),
    ).rejects.toMatchObject({
      status: 403,
      type: "urn:smcp:problem:invalid-api-key-claims",
    });
  });

  it("rejects a personal key", async () => {
    await expect(
      requireApiKey(
        new FakeClerk(managedKey({ subject: "user_test" })),
        "Bearer secret-value",
        "jobs:create",
      ),
    ).rejects.toMatchObject({
      status: 403,
      type: "urn:smcp:problem:organization-required",
    });
  });

  it("rejects missing scope", async () => {
    await expect(
      requireApiKey(
        new FakeClerk(managedKey({ scopes: ["jobs:read"] })),
        "Bearer secret-value",
        "jobs:create",
      ),
    ).rejects.toMatchObject({
      status: 403,
      type: "urn:smcp:problem:insufficient-scope",
    });
  });

  it("maps Clerk verification failure to unauthorized", async () => {
    const clerk = new FakeClerk(managedKey());
    clerk.verifyApiKey = () => Promise.reject(new Error("revoked"));
    await expect(
      requireApiKey(clerk, "Bearer revoked-secret", "jobs:create"),
    ).rejects.toMatchObject({
      status: 401,
      type: "urn:smcp:problem:invalid-api-key",
    });
  });
});
