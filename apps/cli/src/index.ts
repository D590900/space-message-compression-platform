#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { basename } from "node:path";

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
  upload:file --project UUID --file PATH --content-type MIME
  compression:create --project UUID --source UUID --type TYPE --profile PROFILE
  compression:get UUID
  compression:candidates UUID
  compression:cancel UUID
  artifact:download UUID --output PATH
  decompression:create --project UUID --artifact UUID
  decompression:get UUID
  decompression:download UUID --output PATH
  capsule:plan --input plan.json
  capsule:plan:get UUID
  capsule:create --project UUID --plan UUID [--pad true|false]
  capsule:get UUID
  capsule:manifest UUID
  capsule:download UUID --output PATH
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
    case "upload:file": {
      const path = requiredFlag(parsed.flags, "file");
      const body = await readFile(path);
      const sha256 = createHash("sha256").update(body).digest("hex");
      const upload = await client.presignUpload({
        project_id: requiredFlag(parsed.flags, "project"),
        filename: basename(path),
        content_type: requiredFlag(parsed.flags, "content-type"),
        bytes: body.byteLength,
        sha256,
      });
      await client.uploadPresigned(upload, body);
      result = {
        source_object_id: upload.source_object_id,
        bytes: body.byteLength,
        sha256,
        expires_at: upload.expires_at,
      };
      break;
    }
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
    case "compression:candidates":
      result = await client.candidates(requiredPositional(parsed.positional));
      break;
    case "compression:cancel":
      result = await client.cancelCompression(
        requiredPositional(parsed.positional),
      );
      break;
    case "artifact:download": {
      const metadata = await client.artifactDownload(
        requiredPositional(parsed.positional),
      );
      result = await saveDownload(
        client,
        metadata,
        requiredFlag(parsed.flags, "output"),
      );
      break;
    }
    case "decompression:create":
      result = await client.createDecompression({
        project_id: requiredFlag(parsed.flags, "project"),
        artifact_id: requiredFlag(parsed.flags, "artifact"),
      });
      break;
    case "decompression:get":
      result = await client.decompression(
        requiredPositional(parsed.positional),
      );
      break;
    case "decompression:download": {
      const job = await client.decompression(
        requiredPositional(parsed.positional),
      );
      const downloadUrl = requireString(job, "download_url");
      result = await saveDownload(
        client,
        { download_url: downloadUrl },
        requiredFlag(parsed.flags, "output"),
      );
      break;
    }
    case "capsule:plan":
      result = await client.createCapsulePlan(
        JSON.parse(
          await readFile(requiredFlag(parsed.flags, "input"), "utf8"),
        ) as CapsulePlanCreate,
      );
      break;
    case "capsule:plan:get":
      result = await client.capsulePlan(requiredPositional(parsed.positional));
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
    case "capsule:manifest":
      result = await client.capsuleManifest(
        requiredPositional(parsed.positional),
      );
      break;
    case "capsule:download": {
      const metadata = await client.capsuleDownload(
        requiredPositional(parsed.positional),
      );
      result = await saveDownload(
        client,
        metadata,
        requiredFlag(parsed.flags, "output"),
      );
      break;
    }
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

async function saveDownload(
  client: SmcpClient,
  metadata: { download_url: string; sha256?: string | null },
  outputPath: string,
): Promise<Record<string, unknown>> {
  const body = await client.downloadSigned(metadata);
  const sha256 = createHash("sha256").update(body).digest("hex");
  if (metadata.sha256 && metadata.sha256 !== sha256)
    throw new Error("download SHA-256 does not match API metadata");
  await writeFile(outputPath, body, { flag: "wx" });
  return { output: outputPath, bytes: body.byteLength, sha256 };
}

function requireString(value: Record<string, unknown>, key: string): string {
  const result = value[key];
  if (typeof result !== "string")
    throw new Error(`${key} is unavailable; the resource may not be complete`);
  return result;
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
