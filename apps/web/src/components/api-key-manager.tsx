"use client";
import { Check, Copy, KeyRound, LoaderCircle, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

type ApiKey = {
  id: string;
  name: string;
  expiration: number | null;
  revoked: boolean;
  scopes?: string[];
  claims?: { scopes?: string[] };
};
export const defaultApiKeyScopes = [
  "jobs:create",
  "jobs:read",
  "jobs:cancel",
  "artifacts:read",
  "decompressions:create",
  "capsules:plan",
  "capsules:create",
  "capsules:read",
] as const;
export function ApiKeyManager({ keys }: { keys: ApiKey[] }) {
  const router = useRouter();
  const [pending, setPending] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  async function create(data: FormData) {
    try {
      setPending("create");
      setError("");
      const expiration = new Date(String(data.get("expires_at"))).toISOString();
      const response = await fetch("/api/smcp/v1/api-keys", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          name: data.get("name"),
          scopes: defaultApiKeyScopes,
          expires_at: expiration,
        }),
      });
      const body = (await response.json()) as {
        secret?: string;
        detail?: string;
      };
      if (!response.ok || !body.secret)
        throw new Error(body.detail ?? "Key creation failed.");
      setSecret(body.secret);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Key creation failed.",
      );
    } finally {
      setPending("");
    }
  }
  async function revoke(id: string) {
    if (
      !window.confirm(
        "Revoke this API key now? Calls using it will stop immediately.",
      )
    )
      return;
    try {
      setPending(id);
      setError("");
      const response = await fetch(`/api/smcp/v1/api-keys/${id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const body = (await response.json()) as { detail?: string };
        throw new Error(body.detail ?? "Revocation failed.");
      }
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Revocation failed.");
    } finally {
      setPending("");
    }
  }
  async function copy() {
    await navigator.clipboard.writeText(secret);
    setCopied(true);
  }
  return (
    <>
      <section className="settings-section">
        <h2>Issue a scoped key</h2>
        <p>
          Secrets are generated and verified by Clerk. This console never stores
          the one-time value.
        </p>
        <form className="inline-form" action={create}>
          <label>
            <span>Name</span>
            <input
              name="name"
              required
              minLength={2}
              maxLength={80}
              placeholder="production-ingest"
            />
          </label>
          <label>
            <span>Expires at</span>
            <input name="expires_at" type="datetime-local" required />
          </label>
          <div className="scope-summary">
            <strong>Scopes</strong>
            <span>{defaultApiKeyScopes.join(" · ")}</span>
          </div>
          <button className="button button-primary" disabled={pending !== ""}>
            {pending === "create" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <KeyRound size={16} />
            )}
            Create API key
          </button>
        </form>
        {secret && (
          <div className="secret-reveal" role="status">
            <Check size={18} />
            <div>
              <strong>Copy this secret now</strong>
              <p className="mono">{secret}</p>
              <span>It cannot be shown again after leaving this page.</span>
            </div>
            <button className="button button-secondary" onClick={copy}>
              {copied ? <Check size={16} /> : <Copy size={16} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        )}
      </section>
      <section className="settings-section">
        <h2>Active credentials</h2>
        {keys.length === 0 ? (
          <p className="muted">
            No API key has been issued for this organization.
          </p>
        ) : (
          <div className="ruled-list">
            {keys.map((key) => (
              <div className="key-row" key={key.id}>
                <div>
                  <strong>{key.name}</strong>
                  <span className="mono">{key.id}</span>
                </div>
                <div>
                  <span>{key.revoked ? "Revoked" : "Active"}</span>
                  <small className="mono">
                    {key.expiration
                      ? new Date(key.expiration).toLocaleString()
                      : "No expiry"}
                  </small>
                </div>
                <button
                  className="button button-danger"
                  disabled={pending !== "" || key.revoked}
                  onClick={() => revoke(key.id)}
                >
                  {pending === key.id ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Trash2 size={16} />
                  )}
                  Revoke
                </button>
              </div>
            ))}
          </div>
        )}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </section>
    </>
  );
}
