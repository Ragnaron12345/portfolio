import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, reportUrl } from "../lib/api";
import { formatDuration, formatMetric, formatSample } from "../lib/format";
import { navigate } from "../lib/router";
import type { ComparisonData, ExactConfiguration, FailureData, RunSummary } from "../types";
import { ConfigurationDrawer } from "../components/ConfigurationDrawer";
import { Icon } from "../components/Icon";
import { MetricHelp } from "../components/MetricHelp";
import { StatePanel } from "../components/StatePanel";
import { Status } from "../components/Status";
import { PageFrame } from "./OverviewPage";

const OperationalChart = lazy(() => import("../components/OperationalChart"));

export function RunDetailPage({ runId }: { runId: string | null }) {
  const [run, setRun] = useState<RunSummary | null>(null);
  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [regressions, setRegressions] = useState<FailureData | null>(null);
  const [configuration, setConfiguration] = useState<ExactConfiguration | null>(null);
  const [error, setError] = useState<{ message: string; missing: boolean } | null>(null);

  useEffect(() => {
    if (runId) return;
    api<RunSummary[]>("/runs?limit=1").then((items) => {
      if (items[0]) navigate(`/runs/${items[0].id}`, true);
      else setError({ message: "No runs exist yet.", missing: false });
    }).catch((reason: Error) => setError({ message: reason.message, missing: false }));
  }, [runId]);

  const load = useCallback(async () => {
    if (!runId) return;
    try {
      const [runData, comparisonData, regressionData] = await Promise.all([
        api<RunSummary>(`/runs/${runId}`),
        api<ComparisonData>(`/runs/${runId}/comparison`),
        api<FailureData>(`/runs/${runId}/failures?regressions_only=true`),
      ]);
      setRun(runData);
      setComparison(comparisonData);
      setRegressions(regressionData);
      setError(null);
    } catch (reason) {
      setError({ message: reason instanceof Error ? reason.message : "Run unavailable", missing: reason instanceof ApiError && reason.status === 404 });
    }
  }, [runId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!runId || !run || !["queued", "running"].includes(run.status)) return;
    const interval = window.setInterval(() => void load(), 800);
    return () => window.clearInterval(interval);
  }, [load, run, runId]);

  const header = useMemo(() => run ? `${run.status === "running" ? "Running" : run.status === "queued" ? "Queued" : run.status === "completed_with_errors" ? "Completed with errors" : run.status === "completed" ? "Completed" : run.status} — ${run.completed} / ${run.total} — ${run.progress_percent}%` : "Run detail", [run]);

  async function cancel() {
    if (!run) return;
    await api(`/runs/${run.id}/cancel`, { method: "POST" });
    await load();
  }

  if (error) return <PageFrame><StatePanel kind={error.missing ? "empty" : "error"} title={error.missing ? "Selected run no longer exists" : "Run unavailable"} action={<button className="secondary" onClick={() => navigate("/runs")}>Choose another run</button>}>{error.message}. The selection was not replaced automatically.</StatePanel></PageFrame>;
  if (!run || !comparison || !regressions) return <PageFrame><StatePanel kind="loading" title="Loading selected historical run">Polling only {runId ?? "the explicit URL selection"}…</StatePanel></PageFrame>;

  return (
    <div className={configuration ? "run-layout drawer-open" : "run-layout"}>
      <PageFrame>
        <div className="breadcrumb"><button onClick={() => navigate("/runs")}>Runs</button><span>/</span><span>{run.experiment_name}</span><code>{window.location.pathname}</code></div>
        <header className="run-header">
          <div><div className="run-title-line"><Status value={run.status} /><h1>{header}</h1></div><div className="run-progress"><i style={{ width: `${run.progress_percent}%` }} /></div></div>
          <div className="run-header-actions">
            {run.status === "running" || run.status === "queued" ? <button className="danger-button" onClick={cancel}>Cancel run</button> : null}
            <a className="secondary button-link" href={reportUrl(run.id)}><Icon name="download" />Export report</a>
          </div>
        </header>
        <div className="run-counters">
          <span className={run.failed ? "counter danger" : "counter"}>Failures: <b>{run.failed}</b></span>
          <span className="counter warning">Retries: <b>{run.retried}</b></span>
          <span className="counter">Elapsed: <b>{formatDuration(run.elapsed_seconds)}</b></span>
          {run.eta_seconds !== null ? <span className="counter">ETA: <b>{formatDuration(run.eta_seconds)}</b></span> : null}
        </div>
        {run.status === "completed_with_errors" ? <div className="inline-alert partial" role="status"><strong>Partial success.</strong> {run.successful}/{run.total} generations succeeded; {run.failed} failures remain inspectable.</div> : null}
        {run.status === "failed" ? <div className="inline-alert" role="alert"><strong>Run failed.</strong> {run.recovery_note ?? "No case result was completed."}</div> : null}
        <nav className="tab-row" aria-label="Run detail sections"><button className="active">Comparison</button><button onClick={() => navigate(`/failures?runId=${run.id}`)}>Failures <span>{run.failed}</span></button><button onClick={() => setConfiguration(comparison.candidate.configuration)}>Configuration</button></nav>
        <section className="comparison-section">
          <div className="comparison-head">
            <div><span>Exact configurations</span><h2>{comparison.baseline.label}</h2><button onClick={() => setConfiguration(comparison.baseline.configuration)}>View baseline configuration</button></div>
            <div><span>Compared with</span><h2>{comparison.candidate.label}</h2><button onClick={() => setConfiguration(comparison.candidate.configuration)}>View candidate configuration</button></div>
          </div>
          {comparison.metrics.length ? <div className="table-scroll"><table className="data-table metric-table">
            <thead><tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Delta</th></tr></thead>
            <tbody>{comparison.metrics.map((metric) => {
              const delta = metric.delta;
              return <tr key={metric.name}>
                <td><div className="metric-name"><strong>{metric.label}</strong><MetricHelp definition={metric.definition} direction={metric.better_direction} />{metric.metric_type === "judge" ? <em>LLM judge</em> : null}</div><span>{metric.unit} · {metric.better_direction} is better</span></td>
                <td><strong>{formatMetric(metric.baseline?.value ?? null, metric.unit)}</strong><span>{formatSample(metric.baseline)}</span></td>
                <td><strong>{formatMetric(metric.candidate?.value ?? null, metric.unit)}</strong><span>{formatSample(metric.candidate)}</span></td>
                <td><div className={delta.improved === null ? "delta neutral" : delta.improved ? "delta good" : "delta bad"}><b>{delta.absolute === null ? "unavailable" : formatDelta(delta.absolute, delta.display_unit, metric.unit)}</b><span>{delta.relative_percent === null ? "no relative delta" : `${delta.relative_percent > 0 ? "+" : ""}${delta.relative_percent.toFixed(1)}%`}</span><small>{delta.improved === null ? "no change" : delta.improved ? "improvement" : "regression"}</small></div></td>
              </tr>;
            })}</tbody>
          </table></div> : <StatePanel kind="empty" title="Metrics are not available yet">Progress is visible above; completed batches will appear without changing the selected run.</StatePanel>}
        </section>
        {comparison.all_configurations.some((item) => item.metrics.some((metric) => metric.name === "p95_latency")) ? <Suspense fallback={<div className="chart-skeleton">Loading operational chart…</div>}><OperationalChart comparison={comparison} /></Suspense> : null}
        <section className="regressed-section">
          <div className="section-heading"><div><h2>Regressed cases</h2><p>Candidate cases whose composite applicable quality score is below the selected baseline.</p></div><button className="secondary" onClick={() => navigate(`/failures?runId=${run.id}&regressions=1`)}>Open in failures <Icon name="external" /></button></div>
          {regressions.items.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Case ID</th><th>Category</th><th>Failed metric</th><th>Latency</th><th>Cost</th><th /></tr></thead><tbody>{regressions.items.slice(0, 6).map((item) => <tr key={item.id} className="clickable regression-row" onClick={() => navigate(`/failures?runId=${run.id}&regressions=1&case=${item.case_id}`)}><td className="mono">{item.case_id}</td><td>{item.category.replaceAll("_", " ")}</td><td>{item.failed_metrics.map((name) => name.replaceAll("_", " ")).join(", ") || "quality score decreased"}</td><td>{item.latency_ms === null ? "unavailable" : `${item.latency_ms.toFixed(1)} ms`}</td><td>{item.cost_usd === null ? "unavailable" : `$${item.cost_usd.toFixed(6)}`}</td><td><Icon name="chevron" /></td></tr>)}</tbody></table></div> : <div className="empty-row">No pairwise regressions are available for completed candidate cases.</div>}
        </section>
      </PageFrame>
      {configuration ? <ConfigurationDrawer configuration={configuration} onClose={() => setConfiguration(null)} /> : null}
    </div>
  );
}

export function formatDelta(value: number, displayUnit: string, originalUnit: string): string {
  const sign = value > 0 ? "+" : "";
  if (displayUnit === "percentage points") return `${sign}${(value * 100).toFixed(1)} pp`;
  if (originalUnit === "ms") return `${sign}${value.toFixed(1)} ms`;
  if (originalUnit === "USD") return `${sign}$${value.toFixed(5)}`;
  return `${sign}${value.toFixed(2)} ${displayUnit}`;
}
