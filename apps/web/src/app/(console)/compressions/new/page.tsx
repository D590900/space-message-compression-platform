import type { Metadata } from "next";

import { EmptyState } from "../../../../components/empty-state";
import { NewCompressionForm } from "../../../../components/new-compression-form";
import { smcp } from "../../../../lib/smcp";
import type { Page, Project } from "../../../../lib/types";

export const metadata: Metadata = { title: "New compression" };
export default async function NewCompressionPage() {
  const projects = (
    await smcp<Page<Project>>("/v1/projects?limit=100&offset=0")
  ).data;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Compress a source</h1>
          <p>
            Bind an immutable upload to a measured, asynchronous compression
            job.
          </p>
        </div>
      </header>
      {projects.length ? (
        <NewCompressionForm projects={projects} />
      ) : (
        <EmptyState title="A project is required">
          Create a project in settings before uploading source material.
        </EmptyState>
      )}
    </>
  );
}
