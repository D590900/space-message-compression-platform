import {
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  File,
  Plus,
  Search,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState } from "../../../components/empty-state";
import { JobActions } from "../../../components/job-actions";
import { Status } from "../../../components/status";
import { SmcpApiError, smcp } from "../../../lib/smcp";
import type {
  Artifact,
  Candidate,
  Compression,
  CompressionStatus,
  Page,
  Project,
} from "../../../lib/types";

export const metadata: Metadata = { title: "Compressions" };
const terminal = new Set<CompressionStatus>([
  "COMPLETED",
  "FAILED_RETRYABLE",
  "FAILED_TERMINAL",
  "CANCELLED",
]);
const stages = [
  "VALIDATING",
  "ENCODING",
  "MEASURING",
  "SELECTING",
  "PACKAGING",
  "COMPLETED",
] as const;

function formatBytes(value: number | null) {
  if (value === null) return "—";
  return (
    new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value) + "B"
  );
}
function formatDate(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
function viewMatches(status: CompressionStatus, view: string) {
  if (view === "active") return !terminal.has(status);
  if (view === "attention") return status.startsWith("FAILED");
  if (view === "completed") return status === "COMPLETED";
  return true;
}

export default async function CompressionsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const view = typeof query.view === "string" ? query.view : "all";
  const search =
    typeof query.q === "string" ? query.q.trim().toLowerCase() : "";
  const selectedId = typeof query.job === "string" ? query.job : undefined;
  let projects: Project[] = [];
  let failure = "";
  try {
    projects = (await smcp<Page<Project>>("/v1/projects?limit=100&offset=0"))
      .data;
  } catch (error) {
    failure =
      error instanceof SmcpApiError ? error.message : "The API is unavailable.";
  }

  const projectId =
    typeof query.project === "string" ? query.project : projects[0]?.id;
  let jobs: Compression[] = [];
  if (projectId) {
    try {
      jobs = (
        await smcp<Page<Compression>>(
          `/v1/compressions?project_id=${encodeURIComponent(projectId)}&limit=100&offset=0`,
        )
      ).data;
    } catch (error) {
      failure =
        error instanceof SmcpApiError
          ? error.message
          : "Compression jobs could not be loaded.";
    }
  }
  const visible = jobs.filter(
    (job) =>
      viewMatches(job.status, view) &&
      (!search ||
        `${job.id} ${job.input_type} ${job.profile} ${job.status}`
          .toLowerCase()
          .includes(search)),
  );
  const selected = jobs.find((job) => job.id === selectedId) ?? visible[0];
  let candidates: Candidate[] = [];
  let artifacts: Artifact[] = [];
  if (selected && projectId) {
    const [candidateResult, artifactResult] = await Promise.allSettled([
      smcp<{ data: Candidate[] }>(`/v1/compressions/${selected.id}/candidates`),
      smcp<Page<Artifact>>(
        `/v1/artifacts?project_id=${encodeURIComponent(projectId)}&limit=100&offset=0`,
      ),
    ]);
    if (candidateResult.status === "fulfilled")
      candidates = candidateResult.value.data;
    if (artifactResult.status === "fulfilled")
      artifacts = artifactResult.value.data.filter(
        (item) => item.job_id === selected.id,
      );
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Control plane</p>
          <h1>Compression ledger</h1>
          <p>
            Trace every request from source validation to reproducible output.
          </p>
        </div>
        <Link className="button button-primary" href="/compressions/new">
          <Plus size={17} />
          New compression
        </Link>
      </header>
      {failure && (
        <div className="banner banner-danger" role="alert">
          <AlertTriangle size={18} />
          <div>
            <strong>Live evidence unavailable</strong>
            <span>{failure}</span>
          </div>
        </div>
      )}
      <section className="ledger" aria-label="Compression jobs">
        <div className="ledger-toolbar">
          <nav className="saved-views" aria-label="Saved views">
            {["all", "active", "attention", "completed"].map((item) => (
              <Link
                key={item}
                href={`?view=${item}${projectId ? `&project=${projectId}` : ""}`}
                aria-current={view === item ? "page" : undefined}
              >
                {item}
              </Link>
            ))}
          </nav>
          <form className="ledger-filters">
            <input type="hidden" name="view" value={view} />
            <label>
              <span className="sr-only">Project</span>
              <select name="project" defaultValue={projectId}>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="search-field">
              <Search size={16} />
              <span className="sr-only">Search jobs</span>
              <input
                name="q"
                defaultValue={search}
                placeholder="Search ID, type, state"
              />
            </label>
            <button className="button button-secondary" type="submit">
              Apply
            </button>
          </form>
        </div>
        {!projectId ? (
          <EmptyState title="Create a project first">
            A project establishes the tenant boundary, quality policy, and
            retention contract.
            <Link className="text-link" href="/settings">
              Open settings <ArrowRight size={15} />
            </Link>
          </EmptyState>
        ) : visible.length === 0 ? (
          <EmptyState title="No matching records">
            This view contains no compression jobs. Filters reflect live
            platform data only.
          </EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="command-table">
              <thead>
                <tr className="group-head">
                  <th colSpan={2}>Identity</th>
                  <th colSpan={3}>Execution</th>
                  <th colSpan={2}>Evidence</th>
                  <th>Output</th>
                </tr>
                <tr>
                  <th>Record</th>
                  <th>Type</th>
                  <th>Profile</th>
                  <th>Status</th>
                  <th>Requested</th>
                  <th>Candidate</th>
                  <th>Target</th>
                  <th>
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((job) => {
                  const isSelected = selected?.id === job.id;
                  return (
                    <tr
                      key={job.id}
                      className={isSelected ? "selected-row" : undefined}
                    >
                      <td>
                        <Link
                          className="row-link mono"
                          href={`?view=${view}&project=${projectId}&job=${job.id}${search ? `&q=${encodeURIComponent(search)}` : ""}`}
                        >
                          {job.id.slice(0, 12)}
                          <span className="sr-only"> open evidence</span>
                        </Link>
                      </td>
                      <td>{job.input_type.toLowerCase()}</td>
                      <td>{job.profile}</td>
                      <td>
                        <Status value={job.status} />
                      </td>
                      <td className="mono">{formatDate(job.requested_at)}</td>
                      <td className="mono">
                        {job.selected_candidate_id?.slice(0, 10) ?? "pending"}
                      </td>
                      <td className="mono">{formatBytes(job.target_bytes)}</td>
                      <td>
                        <ChevronRight size={17} aria-hidden="true" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {selected && (
          <section
            className="evidence-drawer"
            aria-labelledby="selected-job-title"
          >
            <header>
              <div>
                <p className="eyebrow">Selected record</p>
                <h2 id="selected-job-title">
                  {selected.input_type.toLowerCase()} ·{" "}
                  <span className="mono">{selected.id}</span>
                </h2>
              </div>
              <Status value={selected.status} />
            </header>
            <div className="drawer-grid">
              <section>
                <h3>Lifecycle</h3>
                <ol className="lifecycle">
                  {stages.map((stage) => {
                    const currentIndex = stages.indexOf(
                      selected.status as (typeof stages)[number],
                    );
                    const index = stages.indexOf(stage);
                    const reached =
                      selected.status === "COMPLETED" ||
                      (currentIndex >= index && currentIndex >= 0);
                    return (
                      <li key={stage} className={reached ? "reached" : ""}>
                        <span aria-hidden="true" />
                        {stage.toLowerCase()}{" "}
                        {stage === selected.status && <small>current</small>}
                      </li>
                    );
                  })}
                </ol>
                {selected.error_code && (
                  <p className="inline-error">
                    <AlertTriangle size={15} />
                    {selected.error_code}
                  </p>
                )}
                <dl className="evidence-list">
                  <div>
                    <dt>Requested</dt>
                    <dd className="mono">
                      {formatDate(selected.requested_at)}
                    </dd>
                  </div>
                  <div>
                    <dt>Completed</dt>
                    <dd className="mono">
                      {formatDate(selected.completed_at)}
                    </dd>
                  </div>
                  <div>
                    <dt>Source</dt>
                    <dd className="mono">{selected.source_object_id}</dd>
                  </div>
                </dl>
              </section>
              <section className="candidate-region">
                <h3>
                  Candidate comparison <span>{candidates.length}</span>
                </h3>
                {candidates.length === 0 ? (
                  <p className="muted">
                    No measured candidate has been recorded yet.
                  </p>
                ) : (
                  <div className="table-scroll">
                    <table className="candidate-table">
                      <thead>
                        <tr>
                          <th>Codec</th>
                          <th>Payload</th>
                          <th>Gate</th>
                          <th>Encode</th>
                          <th>Determinism</th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidates.map((candidate) => (
                          <tr
                            key={candidate.id}
                            className={
                              candidate.id === selected.selected_candidate_id
                                ? "winner"
                                : undefined
                            }
                          >
                            <td>
                              <strong className="mono">
                                {candidate.codec_id}
                              </strong>
                              <small>{candidate.codec_version}</small>
                            </td>
                            <td className="mono">
                              {formatBytes(
                                candidate.payload_bytes +
                                  candidate.container_overhead_bytes,
                              )}
                            </td>
                            <td>
                              {candidate.quality_gate_passed
                                ? "Passed"
                                : "Failed"}
                            </td>
                            <td className="mono">
                              {candidate.encode_duration_ms.toFixed(1)} ms
                            </td>
                            <td>
                              {candidate.determinism_status
                                .toLowerCase()
                                .replaceAll("_", " ")}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
              <section>
                <h3>Artifacts & next actions</h3>
                {artifacts.length === 0 ? (
                  <p className="muted">
                    No output artifact is available for this job.
                  </p>
                ) : (
                  <ul className="artifact-list">
                    {artifacts.map((artifact) => (
                      <li key={artifact.id}>
                        <File size={17} />
                        <div>
                          <strong>{artifact.kind.toLowerCase()}</strong>
                          <span className="mono">
                            {formatBytes(artifact.bytes)} ·{" "}
                            {artifact.sha256_hex.slice(0, 14)}…
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <JobActions
                  jobId={selected.id}
                  artifactId={artifacts[0]?.id ?? null}
                  canCancel={!terminal.has(selected.status)}
                />
              </section>
            </div>
          </section>
        )}
      </section>
    </>
  );
}
