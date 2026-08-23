import type { Metadata } from "next";
import { ProjectForm } from "../../../components/project-form";
import { smcp } from "../../../lib/smcp";
import type { Page, Project } from "../../../lib/types";
export const metadata: Metadata = { title: "Settings" };
export default async function SettingsPage() {
  const projects = (
    await smcp<Page<Project>>("/v1/projects?limit=100&offset=0")
  ).data;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Project settings</h1>
          <p>
            Define quality and source-retention boundaries for this
            organization.
          </p>
        </div>
      </header>
      <section className="settings-section">
        <h2>Projects</h2>
        {projects.length ? (
          <div className="ruled-list">
            {projects.map((project) => (
              <dl key={project.id}>
                <div>
                  <dt>Name</dt>
                  <dd>{project.name}</dd>
                </div>
                <div>
                  <dt>Quality policy</dt>
                  <dd className="mono">
                    {Object.keys(project.quality_policy).length
                      ? JSON.stringify(project.quality_policy)
                      : "platform defaults"}
                  </dd>
                </div>
                <div>
                  <dt>Original retention</dt>
                  <dd className="mono">
                    {project.original_retention_seconds === null
                      ? "platform default"
                      : project.original_retention_seconds === 0
                        ? "delete after processing"
                        : `${project.original_retention_seconds}s`}
                  </dd>
                </div>
                <div>
                  <dt>ID</dt>
                  <dd className="mono">{project.id}</dd>
                </div>
              </dl>
            ))}
          </div>
        ) : (
          <p className="muted">No project exists in this organization.</p>
        )}
        <h3>Create project</h3>
        <ProjectForm />
      </section>
    </>
  );
}
