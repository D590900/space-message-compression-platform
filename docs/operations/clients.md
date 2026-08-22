# Supported clients

## TypeScript

The workspace package `@smcp/sdk` is a strict ESM client for browsers and Node.js 24+. It accepts an API origin, a scoped API key and an optional Fetch implementation. Mutation methods generate an idempotency key unless the caller supplies a stable retry key. Non-2xx Problem Details responses raise `SmcpProblem` with status, type and request ID.

```ts
import { SmcpClient } from "@smcp/sdk";

const smcp = new SmcpClient({
  baseUrl: process.env.SMCP_API_URL!,
  apiKey: process.env.SMCP_API_KEY!,
});

const job = await smcp.createCompression(
  {
    project_id: projectId,
    source_object_id: sourceObjectId,
    input_type: "TEXT",
    profile: "faithful",
  },
  { idempotencyKey: "message-2026-08-22" },
);
```

## Python

`packages/sdk-python` contains the dependency-free Python 3.12+ package `smcp-sdk`. It uses the standard library HTTPS client by default and accepts an injected transport for tests or controlled enterprise networking.

```python
from smcp_sdk import SmcpClient

smcp = SmcpClient(api_url, api_key)
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
smcp compression:create --project "$PROJECT_ID" --source "$SOURCE_ID" --type TEXT --profile faithful
smcp capsule:plan --input capsule-plan.json
smcp capsule:create --project "$PROJECT_ID" --plan "$PLAN_ID" --pad false
```
