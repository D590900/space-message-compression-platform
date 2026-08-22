import { describe, expect, it, vi } from "vitest";

import type { ClerkGateway } from "../src/auth.js";
import type { Database } from "../src/database.js";
import { KeyRotationScheduler } from "../src/key-rotation-scheduler.js";

const rotation = {
  id: "5e5e0c52-824a-48ca-aa65-02822fd4499c",
  tenant_subject: "org_test",
  old_key_id: "apikey_old",
  new_key_id: "apikey_new",
  revoke_at: new Date("2026-08-22T00:00:00Z"),
  attempt: 1,
};

describe("key rotation scheduler", () => {
  it("revokes a due old key and completes its durable claim", async () => {
    const database = {
      claimDueApiKeyRotations: vi.fn(() => Promise.resolve([rotation])),
      completeApiKeyRotation: vi.fn(() => Promise.resolve()),
      retryApiKeyRotation: vi.fn(() => Promise.resolve()),
    } as unknown as Database;
    const clerk = {
      revokeApiKey: vi.fn(() => Promise.resolve()),
    } as unknown as ClerkGateway;
    const scheduler = new KeyRotationScheduler(database, clerk, 5_000);

    await scheduler.poll();

    expect(clerk.revokeApiKey).toHaveBeenCalledWith(
      "apikey_old",
      "Rotated to apikey_new",
    );
    expect(database.completeApiKeyRotation).toHaveBeenCalledWith(
      rotation.id,
      expect.any(String),
    );
    expect(database.retryApiKeyRotation).not.toHaveBeenCalled();
  });

  it("releases the claim with a redacted error code after Clerk fails", async () => {
    const database = {
      claimDueApiKeyRotations: vi.fn(() => Promise.resolve([rotation])),
      completeApiKeyRotation: vi.fn(() => Promise.resolve()),
      retryApiKeyRotation: vi.fn(() => Promise.resolve()),
    } as unknown as Database;
    const clerk = {
      revokeApiKey: vi.fn(() => Promise.reject(new TypeError("secret detail"))),
    } as unknown as ClerkGateway;
    const scheduler = new KeyRotationScheduler(database, clerk, 5_000);

    await scheduler.poll();

    expect(database.retryApiKeyRotation).toHaveBeenCalledWith(
      rotation.id,
      expect.any(String),
      "TypeError",
    );
    expect(database.completeApiKeyRotation).not.toHaveBeenCalled();
  });
});
