import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";

const apiOrigin = process.env.API_INTERNAL_ORIGIN ?? "http://127.0.0.1:3001";
const allowed =
  /^\/v1\/(projects|uploads\/presign|compressions(?:\/[^/]+(?:\/candidates|\/cancel)?)?|artifacts(?:\/[^/]+\/download)?|capsules(?:\/[^/]+(?:\/download|\/manifest)?)?|api-keys(?:\/[^/]+(?:\/rotate)?)?)$/;

async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const pathname = `/${path.join("/")}`;
  if (!allowed.test(pathname))
    return Response.json({ detail: "Route not allowed." }, { status: 404 });
  const { getToken } = await auth();
  const token = await getToken();
  if (!token)
    return Response.json(
      { detail: "Authentication required." },
      { status: 401 },
    );
  const length = Number(request.headers.get("content-length") ?? 0);
  if (length > 1_048_576)
    return Response.json(
      { detail: "Control request exceeds 1 MiB." },
      { status: 413 },
    );
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.text();
  const upstream = await fetch(
    `${apiOrigin}${pathname}${request.nextUrl.search}`,
    {
      method: request.method,
      ...(body === undefined ? {} : { body }),
      redirect: "manual",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${token}`,
        ...(body ? { "content-type": "application/json" } : {}),
        ...(request.headers.get("idempotency-key")
          ? { "idempotency-key": request.headers.get("idempotency-key")! }
          : {}),
      },
    },
  );
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
