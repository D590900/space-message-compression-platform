# Supported clients

## TypeScript

The workspace package `@smcp/sdk` is a strict ESM client for browsers and Node.js 24+. It accepts an API origin, a scoped API key and an optional Fetch implementation. Mutation methods generate an idempotency key unless the caller supplies a stable retry key. Non-2xx Problem Details responses raise `SmcpProblem` with status, type and request ID.

```ts
import { SmcpClient } from "@smcp/sdk";

const smcp = new SmcpClient({
  baseUrl: process.env.SMCP_API_URL!,
  apiKey: process.env.SMCP_API_KEY!,
});

const source = await smcp.presignUpload(
  {
    project_id: projectId,
    filename: "message.txt",
    content_type: "text/plain",
    bytes: body.byteLength,
  },
  { idempotencyKey: "upload-message-2026-08-22" },
);
await smcp.uploadPresigned(source, body);

const job = await smcp.createCompression(
  {
    project_id: projectId,
    source_object_id: sourceObjectId,
    input_type: "TEXT",
    profile: "faithful",
  },
  { idempotencyKey: "message-2026-08-22" },
);

const compressed = await smcp.artifactDownload(selectedArtifactId);
const compressedBytes = await smcp.downloadSigned(compressed);
```

## Python

`packages/sdk-python` contains the dependency-free Python 3.12+ package `smcp-sdk`. It uses the standard library HTTPS client by default and accepts an injected transport for tests or controlled enterprise networking.

```python
from smcp_sdk import SmcpClient

smcp = SmcpClient(api_url, api_key)
source = smcp.presign_upload(
    {
        "project_id": project_id,
        "filename": "message.txt",
        "content_type": "text/plain",
        "bytes": len(body),
    },
    idempotency_key="upload-message-2026-08-22",
)
smcp.upload_presigned(source["upload_url"], source["required_headers"], body)
job = smcp.create_compression(
    {
        "project_id": project_id,
        "source_object_id": source_object_id,
        "input_type": "TEXT",
        "profile": "faithful",
    },
    idempotency_key="message-2026-08-22",
)
```

## CLI

Build with `pnpm --filter @smcp/cli build`, then run `node apps/cli/dist/index.js help`. The packaged executable is named `smcp` and reads `SMCP_API_URL` and `SMCP_API_KEY`. Output is JSON on stdout; typed API problems are compact JSON on stderr with exit status 2, while local usage/configuration failures return status 1.

```console
smcp codecs
smcp upload:file --project "$PROJECT_ID" --file message.txt --content-type text/plain
smcp compression:create --project "$PROJECT_ID" --source "$SOURCE_ID" --type TEXT --profile faithful
smcp compression:get "$JOB_ID"
smcp compression:candidates "$JOB_ID"
smcp artifact:download "$ARTIFACT_ID" --output compressed.bin
smcp decompression:create --project "$PROJECT_ID" --artifact "$ARTIFACT_ID"
smcp decompression:get "$DECOMPRESSION_ID"
smcp decompression:download "$DECOMPRESSION_ID" --output reconstructed.txt
smcp capsule:plan --input capsule-plan.json
smcp capsule:plan:get "$PLAN_ID"
smcp capsule:create --project "$PROJECT_ID" --plan "$PLAN_ID" --pad false
smcp capsule:get "$CAPSULE_ID"
smcp capsule:manifest "$CAPSULE_ID"
smcp capsule:download "$CAPSULE_ID" --output capsule.smcp
smcp capsule:verify --project "$PROJECT_ID" --capsule "$CAPSULE_ID"
smcp-capsule verify capsule.smcp
smcp-capsule extract capsule.smcp --kind text --output text-stream.bin
```

Download commands refuse to overwrite an existing output path and verify the SHA-256 supplied by the API when one is available. Signed storage transfers never attach the Clerk API key to the storage origin. Poll the corresponding `get` command until the asynchronous job is `COMPLETED`; clients do not hide retry or timeout policy behind an unbounded polling loop.
