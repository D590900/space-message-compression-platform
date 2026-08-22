import type { FastifyRequest } from "fastify";

export function toWebRequest(
  request: FastifyRequest,
  apiOrigin: string,
): Request {
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    if (Array.isArray(value)) {
      for (const entry of value) headers.append(name, entry);
    } else if (value !== undefined) {
      headers.set(name, String(value));
    }
  }
  return new Request(new URL(request.url, apiOrigin), {
    method: request.method,
    headers,
  });
}
