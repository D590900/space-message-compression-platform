import { timingSafeEqual } from "node:crypto";

import type { FastifyRequest } from "fastify";
import {
  collectDefaultMetrics,
  Counter,
  Histogram,
  Registry,
} from "prom-client";

import type { ApiConfig } from "./config.js";

export class ApiMetrics {
  public readonly registry = new Registry();

  private readonly httpRequests = new Counter({
    name: "smcp_api_http_requests_total",
    help: "Completed API requests.",
    labelNames: ["method", "route", "status_code"] as const,
    registers: [this.registry],
  });

  private readonly httpDuration = new Histogram({
    name: "smcp_api_http_request_duration_seconds",
    help: "API request duration in seconds.",
    labelNames: ["method", "route"] as const,
    buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    registers: [this.registry],
  });

  private readonly apiKeyFailures = new Counter({
    name: "api_key_verification_failures_total",
    help: "Rejected API-key authentication or authorization attempts.",
    labelNames: ["reason"] as const,
    registers: [this.registry],
  });

  private readonly rateLimitRejections = new Counter({
    name: "rate_limit_rejections_total",
    help: "Requests rejected by an API rate or cost limit.",
    labelNames: ["route"] as const,
    registers: [this.registry],
  });

  private readonly jobs = new Counter({
    name: "jobs_total",
    help: "New asynchronous jobs durably accepted by the API.",
    labelNames: ["job_type"] as const,
    registers: [this.registry],
  });

  private readonly plannerIterations = new Counter({
    name: "planner_iterations_total",
    help: "Capsule planner executions.",
    labelNames: ["solver"] as const,
    registers: [this.registry],
  });

  public constructor() {
    collectDefaultMetrics({
      prefix: "smcp_api_process_",
      register: this.registry,
    });
  }

  public observeRequest(
    request: FastifyRequest,
    statusCode: number,
    startedAtNs: bigint,
  ): void {
    const route = request.routeOptions.url ?? "unmatched";
    const labels = { method: request.method, route };
    this.httpRequests.inc({ ...labels, status_code: String(statusCode) });
    this.httpDuration.observe(
      labels,
      Number(process.hrtime.bigint() - startedAtNs) / 1e9,
    );
    if (statusCode === 429) this.rateLimitRejections.inc({ route });
  }

  public recordApiKeyFailure(problemType: string): void {
    const reason = problemType.startsWith("urn:smcp:problem:")
      ? problemType.slice("urn:smcp:problem:".length)
      : "unknown";
    this.apiKeyFailures.inc({ reason });
  }

  public recordJob(jobType: "capsule" | "compression" | "decompression"): void {
    this.jobs.inc({ job_type: jobType });
  }

  public recordPlannerIteration(solver: "exact" | "greedy"): void {
    this.plannerIterations.inc({ solver });
  }
}

export function authorizeMetrics(
  request: FastifyRequest,
  config: ApiConfig,
): boolean {
  const expected = config.METRICS_BEARER_TOKEN;
  if (!expected)
    return config.NODE_ENV !== "production" && request.ip === "127.0.0.1";
  const authorization = request.headers.authorization;
  const supplied = authorization?.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";
  const expectedBytes = Buffer.from(expected);
  const suppliedBytes = Buffer.from(supplied);
  return (
    expectedBytes.length === suppliedBytes.length &&
    timingSafeEqual(expectedBytes, suppliedBytes)
  );
}
