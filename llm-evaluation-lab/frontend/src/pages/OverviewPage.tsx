import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatDate, formatMetric, formatMoney } from "../lib/format";
import { navigate } from "../lib/router";
import type { OverviewData } from "../types";
import { Icon } from "../components/Icon";
import { StatePanel } from "../components/StatePanel";
import { Status } from "../components/Status";

export function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api<OverviewData>("/overview")
      .then((overview) => {
        if (active) setData(overview);
      })
      .catch((reason: Error) => active && setError(reason.message));
    return () => { active = false; };
  }, []);

  if (error) return <PageFrame><StatePanel kind="error" title="Overview unavailable">{error}</StatePanel></PageFrame>;
  if (!data) return <PageFrame><StatePanel kind="loading" title="Loading measured workspace data">Reading persisted runs and metrics…</StatePanel></PageFrame>;
  if (!data.recent_runs.length) return <PageFrame><StatePanel kind="empty" title="No evaluation runs yet" action={<button className="primary" onClick={() => navigate("/experiments/new")}>Build first experiment</button>}>Create a matrix to produce reproducible results.</StatePanel></PageFrame>;

  return (
    <div className="overview-layout">
      <div className="page-column">
        <PageHeader title="Evaluation overview" subtitle={`${data.datasets_registered} datasets · ${data.models_registered} model configurations`} />
        <section className="metric-strip" aria-label="Evaluation overview metrics">
          <OverviewMetric label="Runs this week" value={String(data.runs_this_week)} detail="persisted runs" />
          <OverviewMetric label="Success rate" value={data.success_rate === null ? "unavailable" : formatMetric(data.success_rate, "%")} detail={`${data.success_numerator}/${data.success_denominator} generations`} />
          <OverviewMetric label="Average p95 latency" value={data.average_p95_latency_ms === null ? "unavailable" : formatMetric(data.average_p95_latency_ms, "ms")} detail="across measured runs" />
          <OverviewMetric label="Total spend" value={formatMoney(data.total_spend_usd)} detail="from recorded token usage" />
        </section>
        <section className="table-section">
          <div className="section-heading"><div><h2>Recent runs</h2><p>Immutable results, newest first</p></div><button className="secondary" onClick={() => navigate("/experiments/new")}>New experiment</button></div>
          <div className="table-scroll">
            <table className="data-table run-table">
              <thead><tr><th>Run</th><th>Experiment</th><th>Status</th><th>Progress</th><th>Started</th><th>Cost</th><th><span className="sr-only">Open</span></th></tr></thead>
              <tbody>
                {data.recent_runs.map((run) => (
                  <tr key={run.id} className="clickable" onClick={() => navigate(`/runs/${run.id}`)}>
                    <td className="mono">{run.id}</td>
                    <td><strong>{run.experiment_name}</strong><span>{run.config_snapshot.combinations.length} configurations · {run.config_snapshot.dataset.case_count} cases</span></td>
                    <td><Status value={run.status} /></td>
                    <td><div className="progress-cell"><span className="progress-track"><i style={{ width: `${run.progress_percent}%` }} /></span><b>{run.progress_percent}%</b></div></td>
                    <td>{formatDate(run.started_at ?? run.created_at)}</td>
                    <td>{formatMoney(run.total_cost_usd)}</td>
                    <td><Icon name="chevron" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <aside className="regression-rail">
        <div className="section-heading"><div><h2>Regression watch</h2><p>Cases that worsened against the exact selected baseline</p></div><span className="count-mark">{data.regression_watch.length}</span></div>
        {data.regression_watch.slice(0, 6).map((item) => (
          <button key={item.id} className="regression-item" onClick={() => navigate(`/failures?runId=${data.regression_run_id}&regressions=1&case=${item.case_id}`)}>
            <span><strong>{item.case_id}</strong><em>Regressed</em></span>
            <b>{item.failed_metrics[0]?.replaceAll("_", " ") ?? "quality score"}</b>
            <small>{item.category.replaceAll("_", " ")}</small>
          </button>
        ))}
        {data.regression_watch.length === 0 ? <p className="muted-copy">No pairwise regressions in completed runs.</p> : null}
        {data.regression_run_id ? <button className="text-action" onClick={() => navigate(`/failures?runId=${data.regression_run_id}&regressions=1`)}>View all regressions <Icon name="external" /></button> : null}
      </aside>
    </div>
  );
}

function OverviewMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1>{subtitle ? <p>{subtitle}</p> : null}</div>{actions ? <div className="page-actions">{actions}</div> : null}</header>;
}

export function PageFrame({ children }: { children: React.ReactNode }) {
  return <div className="page-frame">{children}</div>;
}
