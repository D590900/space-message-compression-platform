import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

import { z } from "zod";

import { ApiProblem } from "./problem.js";

const execFileAsync = promisify(execFile);

const plannerResultSchema = z.strictObject({
  solver: z.enum(["exact", "greedy"]),
  actual_bytes: z.number().int().nonnegative(),
  total_utility: z.number().int(),
  included_items: z.number().int().nonnegative(),
  selections: z.array(
    z.strictObject({
      item_id: z.string().min(1),
      candidate_id: z.string().min(1).nullable(),
      bytes: z.number().int().nonnegative(),
      utility: z.number().int(),
      reason: z.string().min(1),
    }),
  ),
});

export type CapsulePlannerRequest = {
  budget_bytes: number;
  fixed_overhead_bytes: number;
  items: {
    id: string;
    required: boolean;
    candidates: { id: string; bytes: number; utility: number }[];
  }[];
};

export type CapsulePlannerResult = z.infer<typeof plannerResultSchema>;

export interface CapsulePlannerGateway {
  plan(request: CapsulePlannerRequest): Promise<CapsulePlannerResult>;
}

export class RustCapsulePlanner implements CapsulePlannerGateway {
  public constructor(private readonly executablePath: string) {}

  public async plan(
    request: CapsulePlannerRequest,
  ): Promise<CapsulePlannerResult> {
    const directory = await mkdtemp(join(tmpdir(), "smcp-plan-"));
    const input = join(directory, "request.json");
    try {
      await writeFile(input, JSON.stringify(request), { mode: 0o600 });
      const { stdout } = await execFileAsync(
        this.executablePath,
        ["plan", "--input", input],
        { encoding: "utf8", maxBuffer: 4 * 1024 * 1024, timeout: 30_000 },
      );
      return plannerResultSchema.parse(JSON.parse(stdout));
    } catch (error) {
      throw new ApiProblem(
        422,
        "Capsule requirements do not fit the declared budget",
        "urn:smcp:problem:capsule-plan-infeasible",
        error instanceof Error ? error.message.slice(0, 500) : undefined,
      );
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }
}
