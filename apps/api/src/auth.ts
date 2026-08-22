import { createClerkClient } from "@clerk/backend";
import type { ApiScope } from "@smcp/schemas";

import type { ApiConfig } from "./config.js";
import { ApiProblem } from "./problem.js";

export type ApiKeyPrincipal = {
  kind: "api_key";
  tenantSubject: string;
  actorSubject: string;
  keyId: string;
  scopes: readonly string[];
};

export type SessionPrincipal = {
  kind: "session";
  tenantSubject: string;
  actorSubject: string;
};

type VerifiedApiKey = {
  id: string;
  subject: string;
  scopes: string[];
  claims: Record<string, unknown> | null;
  createdBy: string | null;
};

export type ManagedApiKey = VerifiedApiKey & {
  name: string;
  description: string | null;
  expiration: number | null;
  expired: boolean;
  revoked: boolean;
  secret?: string | undefined;
};

export type ApiKeyPage = { data: ManagedApiKey[]; totalCount: number };

export interface ClerkGateway {
  verifyApiKey(secret: string): Promise<VerifiedApiKey>;
  authenticateSession(request: Request): Promise<SessionPrincipal | null>;
  createApiKey(input: {
    name: string;
    subject: string;
    createdBy: string;
    scopes: string[];
    claims: Record<string, unknown>;
    secondsUntilExpiration: number;
  }): Promise<ManagedApiKey>;
  listApiKeys(subject: string): Promise<ApiKeyPage>;
  getApiKey(id: string): Promise<ManagedApiKey>;
  getApiKeySecret(id: string): Promise<string>;
  revokeApiKey(id: string, reason: string): Promise<void>;
}

export class ProductionClerkGateway implements ClerkGateway {
  private readonly client;

  public constructor(config: ApiConfig) {
    this.client = createClerkClient({
      secretKey: config.CLERK_SECRET_KEY,
      publishableKey: config.CLERK_PUBLISHABLE_KEY,
    });
  }

  public verifyApiKey(secret: string): Promise<VerifiedApiKey> {
    return this.client.apiKeys.verify(secret);
  }

  public async authenticateSession(
    request: Request,
  ): Promise<SessionPrincipal | null> {
    const state = await this.client.authenticateRequest(request, {
      acceptsToken: "session_token",
    });
    if (!state.isAuthenticated) return null;
    const auth = state.toAuth();
    if (!auth.userId || !auth.orgId) return null;
    return {
      kind: "session",
      actorSubject: auth.userId,
      tenantSubject: auth.orgId,
    };
  }

  public createApiKey(input: {
    name: string;
    subject: string;
    createdBy: string;
    scopes: string[];
    claims: Record<string, unknown>;
    secondsUntilExpiration: number;
  }): Promise<ManagedApiKey> {
    return this.client.apiKeys.create(input);
  }

  public listApiKeys(subject: string): Promise<ApiKeyPage> {
    return this.client.apiKeys.list({
      subject,
      includeInvalid: true,
      limit: 500,
    });
  }

  public getApiKey(id: string): Promise<ManagedApiKey> {
    return this.client.apiKeys.get(id);
  }

  public async getApiKeySecret(id: string): Promise<string> {
    const result = await this.client.apiKeys.getSecret(id);
    return result.secret;
  }

  public async revokeApiKey(id: string, reason: string): Promise<void> {
    await this.client.apiKeys.revoke({
      apiKeyId: id,
      revocationReason: reason,
    });
  }
}

function bearerSecret(authorization: string | undefined): string {
  if (!authorization) {
    throw new ApiProblem(
      401,
      "Authentication required",
      "urn:smcp:problem:unauthorized",
    );
  }
  const match = /^Bearer ([^\s]+)$/.exec(authorization);
  if (!match?.[1]) {
    throw new ApiProblem(
      401,
      "Invalid authorization header",
      "urn:smcp:problem:unauthorized",
    );
  }
  return match[1];
}

export async function requireApiKey(
  clerk: ClerkGateway,
  authorization: string | undefined,
  scope: ApiScope,
): Promise<ApiKeyPrincipal> {
  let key: VerifiedApiKey;
  try {
    key = await clerk.verifyApiKey(bearerSecret(authorization));
  } catch (error) {
    if (error instanceof ApiProblem) throw error;
    throw new ApiProblem(
      401,
      "Invalid API key",
      "urn:smcp:problem:invalid-api-key",
    );
  }

  if (key.claims?.["smcp_issued"] !== true) {
    throw new ApiProblem(
      403,
      "API key was not issued by this service",
      "urn:smcp:problem:invalid-api-key-claims",
    );
  }
  if (!key.subject.startsWith("org_")) {
    throw new ApiProblem(
      403,
      "Organization API key required",
      "urn:smcp:problem:organization-required",
    );
  }
  if (!key.scopes.includes(scope)) {
    throw new ApiProblem(
      403,
      "API key scope is insufficient",
      "urn:smcp:problem:insufficient-scope",
    );
  }

  return {
    kind: "api_key",
    tenantSubject: key.subject,
    actorSubject: key.createdBy ?? key.subject,
    keyId: key.id,
    scopes: key.scopes,
  };
}

export async function requireSession(
  clerk: ClerkGateway,
  request: Request,
): Promise<SessionPrincipal> {
  const session = await clerk.authenticateSession(request);
  if (!session) {
    throw new ApiProblem(
      401,
      "Signed-in organization session required",
      "urn:smcp:problem:session-required",
    );
  }
  return session;
}
