import type { Metadata } from "next";
import { ApiKeyManager } from "../../../components/api-key-manager";
import { smcp } from "../../../lib/smcp";
type ApiKey = {
  id: string;
  name: string;
  expiration: number | null;
  revoked: boolean;
  scopes?: string[];
  claims?: { scopes?: string[] };
};
export const metadata: Metadata = { title: "API keys" };
export default async function ApiKeysPage() {
  const result = await smcp<{ data: ApiKey[] }>("/v1/api-keys");
  return (
    <>
      <header className="page-header">
        <div>
          <h1>API keys</h1>
          <p>
            Create, inspect, rotate, and revoke organization-bound Clerk
            credentials.
          </p>
        </div>
      </header>
      <ApiKeyManager keys={result.data} />
    </>
  );
}
