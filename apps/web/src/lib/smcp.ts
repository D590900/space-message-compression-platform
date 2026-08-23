import { auth } from "@clerk/nextjs/server";

const apiOrigin = process.env.API_INTERNAL_ORIGIN ?? "http://127.0.0.1:3001";

export class SmcpApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function smcp<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const session = await auth();
  const token = await session.getToken();
  if (!token) throw new SmcpApiError(401, "Authentication is required.");

  const response = await fetch(`${apiOrigin}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      accept: "application/json",
      authorization: `Bearer ${token}`,
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as {
      detail?: string;
      message?: string;
    } | null;
    throw new SmcpApiError(
      response.status,
      problem?.detail ??
        problem?.message ??
        `API request failed (${response.status}).`,
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}
