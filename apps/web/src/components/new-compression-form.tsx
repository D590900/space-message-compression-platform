"use client";

import { ArrowLeft, Check, LoaderCircle, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { Project } from "../lib/types";

const accepted =
  "text/plain,image/avif,image/jpeg,image/png,audio/ogg,audio/wav,video/mp4,video/webm";
const typeByMime: Record<string, string> = {
  "text/plain": "TEXT",
  "image/avif": "IMAGE",
  "image/jpeg": "IMAGE",
  "image/png": "IMAGE",
  "audio/ogg": "AUDIO",
  "audio/wav": "AUDIO",
  "video/mp4": "VIDEO",
  "video/webm": "VIDEO",
};

async function control(path: string, body: unknown) {
  const response = await fetch(`/api/smcp${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "idempotency-key": crypto.randomUUID(),
    },
    body: JSON.stringify(body),
  });
  const value = (await response.json().catch(() => null)) as Record<
    string,
    unknown
  > | null;
  if (!response.ok)
    throw new Error(
      (value?.detail as string | undefined) ?? "The request failed.",
    );
  return value ?? {};
}

async function sha256(file: File) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await file.arrayBuffer(),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function NewCompressionForm({ projects }: { projects: Project[] }) {
  const router = useRouter();
  const [state, setState] = useState<
    "idle" | "hashing" | "uploading" | "creating"
  >("idle");
  const [error, setError] = useState("");
  async function submit(formData: FormData) {
    const file = formData.get("file");
    if (!(file instanceof File) || !file.size)
      return setError("Choose a non-empty supported file.");
    const inputType = typeByMime[file.type];
    if (!inputType)
      return setError(
        "This MIME type is not supported by the secure upload contract.",
      );
    try {
      setError("");
      setState("hashing");
      const digest = await sha256(file);
      setState("uploading");
      const presign = await control("/v1/uploads/presign", {
        project_id: formData.get("project_id"),
        filename: file.name,
        content_type: file.type,
        bytes: file.size,
        sha256: digest,
      });
      const headers = presign.required_headers as Record<string, string>;
      const upload = await fetch(presign.upload_url as string, {
        method: "PUT",
        headers,
        body: file,
      });
      if (!upload.ok)
        throw new Error(`Direct upload failed (${upload.status}).`);
      setState("creating");
      const job = await control("/v1/compressions", {
        project_id: formData.get("project_id"),
        source_object_id: presign.source_object_id,
        input_type: inputType,
        profile: formData.get("profile"),
        ...(formData.get("target_bytes")
          ? { target_bytes: Number(formData.get("target_bytes")) }
          : {}),
      });
      router.push(
        `/compressions?project=${formData.get("project_id")}&job=${job.id}`,
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Compression could not be created.",
      );
      setState("idle");
    }
  }
  return (
    <form className="compose-form" action={submit}>
      <div className="form-grid">
        <label>
          <span>Project</span>
          <select name="project_id" required>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Profile</span>
          <select name="profile" defaultValue="faithful">
            <option value="faithful">Faithful</option>
            <option value="ultra">Ultra</option>
            <option disabled value="semantic">
              Semantic — unavailable
            </option>
          </select>
          <small>
            Unavailable until a verified decoder and immutable weights are
            enabled.
          </small>
        </label>
        <label>
          <span>
            Target bytes <em>optional</em>
          </span>
          <input
            name="target_bytes"
            type="number"
            min="1"
            step="1"
            inputMode="numeric"
            placeholder="e.g. 250000"
          />
        </label>
      </div>
      <label className="file-drop">
        <Upload size={24} />
        <strong>Choose source file</strong>
        <span>Text, AVIF, JPEG, PNG, OGG, WAV, MP4, or WebM</span>
        <input name="file" type="file" accept={accepted} required />
      </label>
      <div className="security-note">
        <Check size={17} />
        <p>
          <strong>Direct, integrity-bound upload.</strong> The console hashes
          the file locally and uploads it directly to private object storage.
          Source bytes never transit this web service.
        </p>
      </div>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <div className="form-actions">
        <Link className="button button-secondary" href="/compressions">
          <ArrowLeft size={16} />
          Cancel
        </Link>
        <button className="button button-primary" disabled={state !== "idle"}>
          {state !== "idle" && <LoaderCircle size={16} className="spin" />}
          {state === "idle"
            ? "Start compression"
            : state === "hashing"
              ? "Hashing locally…"
              : state === "uploading"
                ? "Uploading directly…"
                : "Creating job…"}
        </button>
      </div>
    </form>
  );
}
