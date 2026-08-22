import { createHmac } from "node:crypto";

import { describe, expect, it } from "vitest";

import { SecretBox } from "../src/secret-box.js";
import { webhookSignature } from "../src/webhook-dispatcher.js";
import { resolvePublicWebhookUrl } from "../src/webhook-url.js";

const encryptionKey = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=";

describe("webhook security", () => {
  it("encrypts endpoint secrets with authenticated encryption", () => {
    const box = new SecretBox(encryptionKey);
    const envelope = box.encrypt("whsec_example");
    expect(envelope.toString()).not.toContain("whsec_example");
    expect(box.decrypt(envelope)).toBe("whsec_example");

    envelope[envelope.length - 1] ^= 1;
    expect(() => box.decrypt(envelope)).toThrow();
  });

  it("signs the stable event id, timestamp, and exact body", () => {
    const expected = createHmac("sha256", "whsec_example")
      .update('event_1.1700000000.{"ok":true}')
      .digest("base64");
    expect(
      webhookSignature("whsec_example", "event_1", "1700000000", '{"ok":true}'),
    ).toBe(expected);
  });

  it("rejects private destinations and nonstandard ports", async () => {
    await expect(
      resolvePublicWebhookUrl("https://127.0.0.1/hook"),
    ).rejects.toMatchObject({
      type: "urn:smcp:problem:unsafe-webhook-url",
    });
    await expect(
      resolvePublicWebhookUrl("https://[::1]/hook"),
    ).rejects.toMatchObject({
      type: "urn:smcp:problem:unsafe-webhook-url",
    });
    await expect(
      resolvePublicWebhookUrl("https://example.com:8443/hook"),
    ).rejects.toMatchObject({
      type: "urn:smcp:problem:unsafe-webhook-url",
    });
  });

  it("accepts an explicitly public HTTPS address", async () => {
    await expect(
      resolvePublicWebhookUrl("https://8.8.8.8/hook"),
    ).resolves.toMatchObject({ address: "8.8.8.8", family: 4 });
  });
});
