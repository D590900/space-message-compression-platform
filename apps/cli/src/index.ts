#!/usr/bin/env node
import { readFile } from "node:fs/promises";

import {
  SmcpClient,
  SmcpProblem,
  type CapsulePlanCreate,
  type CompressionCreate,
} from "@smcp/sdk";

import { parseArguments, requiredFlag } from "./arguments.js";

const USAGE = `smcp <command> [options]

Commands:
  codecs
  models
  compression:create --project UUID --source UUID --type TYPE --profile PROFILE
  compression:get UUID
  capsule:plan --input plan.json
  capsule:create --project UUID --plan UUID [--pad true|false]
  capsule:get UUID
  capsule:verify --project UUID --capsule UUID
  usage --project UUID

Environment:
  SMCP_API_URL   API origin (default http://localhost:3001)
  SMCP_API_KEY   required scoped API key
`;

async function run(): Promise<void> {
  const parsed = parseArguments(process.argv.slice(2));
  if (!parsed.command || parsed.command === "help") {
    process.stdout.write(USAGE);
    return;
  }
  const apiKey = process.env["SMCP_API_KEY"];
  if (!apiKey) throw new Error("SMCP_API_KEY is required");
  const client = new SmcpClient({
    baseUrl: process.env["SMCP_API_URL"] ?? "http://localhost:3001",
    apiKey,
  });
  let result: unknown;
  switch (parsed.command) {
    case "codecs":
      result = await client.codecs();
      break;
    case "models":
      result = await client.models();
      break;
    case "compression:create":
      result = await client.createCompression({
        project_id: requiredFlag(parsed.flags, "project"),
        source_object_id: requiredFlag(parsed.flags, "source"),
        input_type: requiredFlag(
          parsed.flags,
          "type",
        ) as CompressionCreate["input_type"],
        profile: requiredFlag(
          parsed.flags,
          "profile",
        ) as CompressionCreate["profile"],
      });
      break;
    case "compression:get":
      result = await client.compression(requiredPositional(parsed.positional));
      break;
    case "capsule:plan":
      result = await client.createCapsulePlan(
        JSON.parse(
          await readFile(requiredFlag(parsed.flags, "input"), "utf8"),
        ) as CapsulePlanCreate,
      );
      break;
    case "capsule:create":
      result = await client.createCapsule({
        project_id: requiredFlag(parsed.flags, "project"),
        plan_id: requiredFlag(parsed.flags, "plan"),
        pad_to_budget: parsed.flags["pad"] === "true",
      });
      break;
    case "capsule:get":
      result = await client.capsule(requiredPositional(parsed.positional));
      break;
    case "capsule:verify":
      result = await client.verifyCapsule({
        project_id: requiredFlag(parsed.flags, "project"),
        capsule_id: requiredFlag(parsed.flags, "capsule"),
      });
      break;
    case "usage":
      result = await client.projectUsage(requiredFlag(parsed.flags, "project"));
      break;
    default:
      throw new Error(`unknown command: ${parsed.command}`);
  }
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

function requiredPositional(values: string[]): string {
  if (!values[0]) throw new Error("resource id is required");
  return values[0];
}

try {
  await run();
} catch (error) {
  if (error instanceof SmcpProblem) {
    process.stderr.write(
      `${JSON.stringify({ error: error.message, status: error.status, type: error.type, request_id: error.requestId })}\n`,
    );
    process.exitCode = 2;
  } else {
    process.stderr.write(
      `${error instanceof Error ? error.message : "unknown error"}\n`,
    );
    process.exitCode = 1;
  }
}
