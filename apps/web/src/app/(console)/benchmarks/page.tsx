import results from "../../../../../../benchmarks/reports/macos-arm64-2026-08-22/results.json";
import type { Metadata } from "next";
export const metadata: Metadata = { title: "Benchmarks" };
export default function BenchmarksPage() {
  const attempts = results.attempts.filter(
    (item) => item.enabled && item.success,
  );
  const failedGates = attempts.filter(
    (item) => !item.quality_gate_passed,
  ).length;
  const groups = Object.groupBy(attempts, (item) => item.content_type);
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Benchmark report</h1>
          <p>
            Measured synthetic fixtures from commit{" "}
            <span className="mono">
              {results.environment.commit.slice(0, 12)}
            </span>
            ; no extrapolated claims.
          </p>
        </div>
      </header>
      <section className="report-meta">
        <dl>
          <div>
            <dt>Generated</dt>
            <dd className="mono">
              {new Date(results.generated_at_utc).toLocaleString()}
            </dd>
          </div>
          <div>
            <dt>Platform</dt>
            <dd>{results.environment.platform}</dd>
          </div>
          <div>
            <dt>Dataset manifest</dt>
            <dd className="mono">
              {results.dataset_manifest_sha256.slice(0, 18)}…
            </dd>
          </div>
          <div>
            <dt>Successful attempts</dt>
            <dd className="mono">{attempts.length}</dd>
          </div>
          <div>
            <dt>Failed quality gates</dt>
            <dd className="mono">{failedGates}</dd>
          </div>
        </dl>
      </section>
      <div className="benchmark-groups">
        {Object.entries(groups).map(([kind, items]) => (
          <section key={kind}>
            <h2>{kind.toLowerCase()}</h2>
            <div className="table-scroll ruled-table">
              <table>
                <thead>
                  <tr>
                    <th>Fixture</th>
                    <th>Codec</th>
                    <th>Payload</th>
                    <th>Ratio</th>
                    <th>Encode</th>
                    <th>Gate</th>
                  </tr>
                </thead>
                <tbody>
                  {items?.map((item, index) => (
                    <tr key={`${item.fixture}-${item.codec_id}-${index}`}>
                      <td>{item.fixture}</td>
                      <td className="mono">{item.codec_id}</td>
                      <td className="mono">
                        {item.output_payload_bytes.toLocaleString()} B
                      </td>
                      <td className="mono">{item.ratio.toFixed(2)}×</td>
                      <td className="mono">{item.encode_ms.toFixed(1)} ms</td>
                      <td>{item.quality_gate_passed ? "Passed" : "Failed"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
