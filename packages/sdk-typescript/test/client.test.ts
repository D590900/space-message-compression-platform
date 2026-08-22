import { describe, expect, it, vi } from "vitest";

import { SmcpClient, SmcpProblem } from "../src/index.js";

describe("SmcpClient", () => {
  it("adds bearer auth and an idempotency key to mutations", async () => {
    const fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ id: "job_1" }), { status: 202 }),
      ),
    );
    const client = new SmcpClient({
      baseUrl: "https://api.example.com",
      apiKey: "smcp_secret",
      fetch,
    });
    await client.createCompression(
      {
        project_id: "project",
        source_object_id: "source",
        input_type: "TEXT",
        profile: "faithful",
      },
      { idempotencyKey: "request-0001" },
    );

    const [url, init] = fetch.mock.calls[0]!;
    expect(String(url)).toBe("https://api.example.com/v1/compressions");
    expect(new Headers(init?.headers).get("authorization")).toBe(
      "Bearer smcp_secret",
    );
    expect(new Headers(init?.headers).get("idempotency-key")).toBe(
      "request-0001",
    );
  });

  it("raises a typed Problem Details error", async () => {
    const fetch = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            type: "urn:smcp:problem:quota-exceeded",
            title: "Quota exceeded",
            status: 429,
            request_id: "request_1",
          }),
          { status: 429 },
        ),
      ),
    );
    const client = new SmcpClient({
      baseUrl: "https://api.example.com",
      apiKey: "smcp_secret",
      fetch,
    });

    await expect(client.codecs()).rejects.toMatchObject<Partial<SmcpProblem>>({
      status: 429,
      type: "urn:smcp:problem:quota-exceeded",
      requestId: "request_1",
    });
  });
});
