import type { FastifyReply, FastifyRequest } from "fastify";
import { ZodError } from "zod";

export class ApiProblem extends Error {
  public constructor(
    public readonly status: number,
    public readonly title: string,
    public readonly type: string,
    message?: string,
  ) {
    super(message ?? title);
    this.name = "ApiProblem";
  }
}

export function registerProblemHandler(
  request: FastifyRequest,
  reply: FastifyReply,
  error: unknown,
): void {
  if (error instanceof ZodError) {
    void reply
      .status(400)
      .type("application/problem+json")
      .send({
        type: "urn:smcp:problem:invalid-request",
        title: "Invalid request",
        status: 400,
        detail: error.issues
          .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
          .join("; "),
        instance: request.url,
        request_id: request.id,
      });
    return;
  }

  const problem =
    error instanceof ApiProblem
      ? error
      : new ApiProblem(
          500,
          "Internal server error",
          "urn:smcp:problem:internal",
        );

  if (!(error instanceof ApiProblem)) {
    request.log.error({ err: error }, "unhandled request error");
  }

  void reply
    .status(problem.status)
    .type("application/problem+json")
    .send({
      type: problem.type,
      title: problem.title,
      status: problem.status,
      ...(problem.status < 500 ? { detail: problem.message } : {}),
      instance: request.url,
      request_id: request.id,
    });
}
