"use client";
import { LoaderCircle, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
export function ProjectForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(data: FormData) {
    try {
      setPending(true);
      setError("");
      const response = await fetch("/api/smcp/v1/projects", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          name: data.get("name"),
        }),
      });
      const body = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(body.detail ?? "Project creation failed.");
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Project creation failed.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <form className="inline-form" action={submit}>
      <label>
        <span>Project name</span>
        <input
          name="name"
          minLength={2}
          maxLength={80}
          required
          placeholder="Operations"
        />
      </label>
      <button className="button button-primary" disabled={pending}>
        {pending ? (
          <LoaderCircle size={16} className="spin" />
        ) : (
          <Plus size={16} />
        )}
        Create project
      </button>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
