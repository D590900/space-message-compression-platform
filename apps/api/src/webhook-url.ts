import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

import { ApiProblem } from "./problem.js";

export type ResolvedWebhookUrl = {
  url: URL;
  address: string;
  family: 4 | 6;
};

function publicIpv4(address: string): boolean {
  const parts = address.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part)))
    return false;
  const [a = 0, b = 0, c = 0] = parts;
  return !(
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 0) ||
    (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19)) ||
    (a === 198 && b === 51 && c === 100) ||
    (a === 203 && b === 0 && c === 113) ||
    a >= 224
  );
}

function publicIpv6(address: string): boolean {
  const normalized = address.toLowerCase();
  if (normalized.startsWith("::ffff:"))
    return publicIpv4(normalized.slice("::ffff:".length));
  return !(
    normalized === "::" ||
    normalized === "::1" ||
    normalized.startsWith("fc") ||
    normalized.startsWith("fd") ||
    /^fe[89ab]/.test(normalized) ||
    normalized.startsWith("ff") ||
    normalized.startsWith("2001:db8:")
  );
}

export async function resolvePublicWebhookUrl(
  value: string,
): Promise<ResolvedWebhookUrl> {
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.hash ||
    (url.port && url.port !== "443")
  ) {
    throw new ApiProblem(
      422,
      "Webhook URL must be a credential-free HTTPS URL on port 443",
      "urn:smcp:problem:unsafe-webhook-url",
    );
  }
  const hostname = url.hostname.replace(/^\[|\]$/g, "");
  const literalFamily = isIP(hostname);
  let resolved: { address: string; family: number };
  try {
    resolved = literalFamily
      ? { address: hostname, family: literalFamily }
      : await lookup(hostname, { verbatim: true });
  } catch {
    throw new ApiProblem(
      422,
      "Webhook hostname could not be resolved",
      "urn:smcp:problem:unsafe-webhook-url",
    );
  }
  const isPublic =
    resolved.family === 4
      ? publicIpv4(resolved.address)
      : publicIpv6(resolved.address);
  if (!isPublic) {
    throw new ApiProblem(
      422,
      "Webhook URL must resolve to a public network address",
      "urn:smcp:problem:unsafe-webhook-url",
    );
  }
  return { url, address: resolved.address, family: resolved.family as 4 | 6 };
}
