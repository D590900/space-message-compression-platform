import type { Metadata } from "next";
import { DownloadButton } from "../../../components/download-button";
import { EmptyState } from "../../../components/empty-state";
import { Status } from "../../../components/status";
import { smcp } from "../../../lib/smcp";
import type { Capsule, Page, Project } from "../../../lib/types";
export const metadata: Metadata = { title: "Capsules" };
export default async function CapsulesPage() {
  const projects = (
    await smcp<Page<Project>>("/v1/projects?limit=100&offset=0")
  ).data;
  const pages = await Promise.all(
    projects.map((p) =>
      smcp<Page<Capsule>>(`/v1/capsules?project_id=${p.id}&limit=100&offset=0`),
    ),
  );
  const capsules = pages.flatMap((p) => p.data);
  const completed = capsules.filter(
    (item) => item.status === "COMPLETED",
  ).length;
  const overBudget = capsules.filter(
    (item) =>
      item.actual_bytes !== null && item.actual_bytes > item.budget_bytes,
  ).length;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Capsules</h1>
          <p>
            Budget compliance, content hashes, and Merkle evidence for each
            binary container.
          </p>
        </div>
      </header>
      {capsules.length > 0 && (
        <section className="report-meta" aria-label="Capsule evidence summary">
          <dl>
            <div>
              <dt>Total records</dt>
              <dd className="mono">{capsules.length}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd className="mono">{completed}</dd>
            </div>
            <div>
              <dt>Incomplete</dt>
              <dd className="mono">{capsules.length - completed}</dd>
            </div>
            <div>
              <dt>Over budget</dt>
              <dd className="mono">{overBudget}</dd>
            </div>
          </dl>
        </section>
      )}
      {!capsules.length ? (
        <EmptyState title="No capsules built">
          Capsule plans and builds will appear only after the API records them.
        </EmptyState>
      ) : (
        <div className="table-scroll ruled-table">
          <table>
            <thead>
              <tr>
                <th>Capsule</th>
                <th>Status</th>
                <th>Actual / budget</th>
                <th>Merkle root</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {capsules.map((item) => (
                <tr key={item.id}>
                  <td className="mono">{item.id.slice(0, 12)}</td>
                  <td>
                    <Status value={item.status} />
                  </td>
                  <td className="mono">
                    {item.actual_bytes?.toLocaleString() ?? "—"} /{" "}
                    {item.budget_bytes.toLocaleString()} B
                  </td>
                  <td className="mono">
                    {item.merkle_root_hex?.slice(0, 18) ?? "pending"}
                  </td>
                  <td>
                    {item.status === "COMPLETED" && (
                      <DownloadButton
                        path={`/v1/capsules/${item.id}/download`}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
