"use client";
import { Download, LoaderCircle } from "lucide-react";
import { useState } from "react";
export function DownloadButton({
  path,
  label = "Download",
}: {
  path: string;
  label?: string;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function run() {
    try {
      setPending(true);
      setError("");
      const response = await fetch(`/api/smcp${path}`);
      const body = (await response.json()) as {
        download_url?: string;
        detail?: string;
      };
      if (!response.ok || !body.download_url)
        throw new Error(body.detail ?? "No download is available.");
      window.location.assign(body.download_url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Download failed.");
    } finally {
      setPending(false);
    }
  }
  return (
    <div>
      <button
        className="button button-secondary"
        onClick={run}
        disabled={pending}
      >
        {pending ? (
          <LoaderCircle size={16} className="spin" />
        ) : (
          <Download size={16} />
        )}
        {label}
      </button>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
