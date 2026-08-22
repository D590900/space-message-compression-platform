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

  it("transfers bytes through signed storage URLs without API credentials", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(new Response(undefined, { status: 200 }))
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2, 3]), { status: 200 }),
      );
    const client = new SmcpClient({
      baseUrl: "https://api.example.com",
      apiKey: "smcp_secret",
      fetch,
    });
    await client.uploadPresigned(
      {
        upload_url: "https://storage.example.com/upload",
        required_headers: { "content-type": "text/plain" },
      },
      new Uint8Array([1, 2, 3]),
    );
    const downloaded = await client.downloadSigned({
      download_url: "https://storage.example.com/download",
    });

    expect([...downloaded]).toEqual([1, 2, 3]);
    expect(String(fetch.mock.calls[0]![0])).toBe(
      "https://storage.example.com/upload",
    );
    expect(
      new Headers(fetch.mock.calls[0]![1]?.headers).has("authorization"),
    ).toBe(false);
    expect(String(fetch.mock.calls[1]![0])).toBe(
      "https://storage.example.com/download",
    );
  });
});
