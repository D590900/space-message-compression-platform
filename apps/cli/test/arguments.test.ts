import { describe, expect, it } from "vitest";

import { parseArguments, requiredFlag } from "../src/arguments.js";

describe("CLI arguments", () => {
  it("separates positionals and flags without evaluating a shell", () => {
    expect(
      parseArguments([
        "capsule:create",
        "id",
        "--project",
        "project",
        "--pad",
        "true",
      ]),
    ).toEqual({
      command: "capsule:create",
      positional: ["id"],
      flags: { project: "project", pad: "true" },
    });
  });

  it("rejects missing flag values", () => {
    expect(() => parseArguments(["usage", "--project"])).toThrow();
    expect(() => requiredFlag({}, "project")).toThrow();
  });
});
