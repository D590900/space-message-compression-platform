export type SmcpClientOptions = {
  baseUrl: string;
  apiKey: string;
  fetch?: typeof globalThis.fetch;
};

export type RequestOptions = {
  idempotencyKey?: string | undefined;
  signal?: AbortSignal | undefined;
};

export type Page<T> = { total_count: number; data: T[] };

export type CompressionCreate = {
  project_id: string;
  source_object_id: string;
  input_type: "TEXT" | "IMAGE" | "AUDIO" | "VIDEO";
  profile: "faithful" | "ultra" | "semantic";
  target_bytes?: number;
};

export type CapsulePlanCreate = {
  project_id: string;
  budget_bytes?: number;
  ecc_percent?: number;
  items: { job_id: string; required: boolean; utility: number }[];
};

export type WebhookCreate = {
  project_id: string;
  url: string;
  event_types: (
    | "compression.completed"
    | "decompression.completed"
    | "capsule.completed"
  )[];
};

export class SmcpProblem extends Error {
  public constructor(
    public readonly status: number,
    public readonly type: string,
    public readonly requestId: string | undefined,
    message: string,
    public readonly body: unknown,
  ) {
    super(message);
    this.name = "SmcpProblem";
  }
}

export class SmcpClient {
  private readonly baseUrl: URL;
  private readonly fetchImplementation: typeof globalThis.fetch;

  public constructor(private readonly options: SmcpClientOptions) {
    this.baseUrl = new URL(
      options.baseUrl.endsWith("/") ? options.baseUrl : `${options.baseUrl}/`,
    );
    this.fetchImplementation = options.fetch ?? globalThis.fetch;
  }

  public codecs(signal?: AbortSignal): Promise<Page<Record<string, unknown>>> {
    return this.request("GET", "v1/codecs", undefined, { signal });
  }

  public models(signal?: AbortSignal): Promise<Page<Record<string, unknown>>> {
    return this.request("GET", "v1/models", undefined, { signal });
  }

  public presignUpload(
    input: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/uploads/presign", input, options);
  }

  public createCompression(
    input: CompressionCreate,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/compressions", input, options);
  }

  public compression(
    id: string,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "GET",
      `v1/compressions/${encodeURIComponent(id)}`,
      undefined,
      {
        signal,
      },
    );
  }

  public candidates(
    id: string,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "GET",
      `v1/compressions/${encodeURIComponent(id)}/candidates`,
      undefined,
      { signal },
    );
  }

  public createDecompression(
    input: { project_id: string; artifact_id: string },
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/decompressions", input, options);
  }

  public createCapsulePlan(
    input: CapsulePlanCreate,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/capsule-plans", input, options);
  }

  public createCapsule(
    input: { project_id: string; plan_id: string; pad_to_budget?: boolean },
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/capsules", input, options);
  }

  public capsule(
    id: string,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "GET",
      `v1/capsules/${encodeURIComponent(id)}`,
      undefined,
      {
        signal,
      },
    );
  }

  public verifyCapsule(
    input: { project_id: string; capsule_id: string },
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/capsules/verify", input, { signal });
  }

  public projectUsage(
    projectId: string,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.request(
      "GET",
      `v1/projects/${encodeURIComponent(projectId)}/usage`,
      undefined,
      { signal },
    );
  }

  public createWebhook(
    input: WebhookCreate,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("POST", "v1/webhooks", input, options);
  }

  private async request<T>(
    method: "GET" | "POST" | "DELETE",
    path: string,
    body?: unknown,
    options: RequestOptions = {},
  ): Promise<T> {
    const headers = new Headers({
      authorization: `Bearer ${this.options.apiKey}`,
      accept: "application/json",
    });
    if (body !== undefined) headers.set("content-type", "application/json");
    if (method !== "GET")
      headers.set(
        "idempotency-key",
        options.idempotencyKey ?? globalThis.crypto.randomUUID(),
      );
    const request: RequestInit = { method, headers };
    if (body !== undefined) request.body = JSON.stringify(body);
    if (options.signal) request.signal = options.signal;
    const response = await this.fetchImplementation(
      new URL(path, this.baseUrl),
      request,
    );
    if (response.status === 204) return undefined as T;
    const responseBody: unknown = await response.json().catch(() => undefined);
    if (!response.ok) {
      const problem = responseBody as
        | {
            type?: string;
            title?: string;
            detail?: string;
            request_id?: string;
          }
        | undefined;
      throw new SmcpProblem(
        response.status,
        problem?.type ?? "about:blank",
        problem?.request_id,
        problem?.detail ??
          problem?.title ??
          `SMCP request failed with ${response.status}`,
        responseBody,
      );
    }
    return responseBody as T;
  }
}
