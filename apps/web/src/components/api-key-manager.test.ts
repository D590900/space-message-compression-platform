import { describe, expect, it } from "vitest";

import { defaultApiKeyScopes } from "./api-key-manager";

describe("default API-key scopes", () => {
  it("covers the complete compression-to-capsule vertical slice", () => {
    expect(defaultApiKeyScopes).toEqual([
      "jobs:create",
      "jobs:read",
      "jobs:cancel",
      "artifacts:read",
      "decompressions:create",
      "capsules:plan",
      "capsules:create",
      "capsules:read",
    ]);
  });
});
