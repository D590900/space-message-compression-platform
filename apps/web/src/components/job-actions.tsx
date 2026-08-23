"use client";

import { Download, LoaderCircle, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`/api/smcp${path}`, init);
  const value = (await response.json().catch(() => null)) as {
    download_url?: string;
    detail?: string;
  } | null;
  if (!response.ok)
    throw new Error(value?.detail ?? "The action could not be completed.");
  return value;
}

export function JobActions({
  jobId,
  artifactId,
  canCancel,
}: {
  jobId: string;
  artifactId: string | null;
  canCancel: boolean;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<"download" | "cancel" | null>(null);
  const [error, setError] = useState("");

  async function download() {
    if (!artifactId) return;
    try {
      setPending("download");
      setError("");
      const result = await api(`/v1/artifacts/${artifactId}/download`);
      if (result?.download_url) window.location.assign(result.download_url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Download failed.");
    } finally {
      setPending(null);
    }
  }

  async function cancel() {
    try {
      setPending("cancel");
      setError("");
      await api(`/v1/compressions/${jobId}/cancel`, {
        method: "POST",
        headers: { "idempotency-key": crypto.randomUUID() },
      });
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Cancellation failed.",
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="action-stack">
      {artifactId && (
        <button
          className="button button-primary"
          onClick={download}
          disabled={pending !== null}
        >
          {pending === "download" ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <Download size={16} />
          )}
          Download artifact
        </button>
      )}
      {canCancel && (
        <button
          className="button button-danger"
          onClick={cancel}
          disabled={pending !== null}
        >
          {pending === "cancel" ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <X size={16} />
          )}
          Cancel job
        </button>
      )}
      {!artifactId && !canCancel && (
        <p className="muted">No valid action is available for this state.</p>
      )}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
