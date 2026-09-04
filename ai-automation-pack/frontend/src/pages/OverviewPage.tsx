import { useMemo } from "react";
import { client } from "../api/client";
import { Icon } from "../components/Icon";
import { Timeline } from "../components/Timeline";
import {
  Button,
  EmptyState,
  ErrorBanner,
  LoadingRows,
  PageHeader,
  SectionHeader,
  StatusMark,
  formatDuration,
  formatPercent,
  formatTime,
} from "../components/Ui";
import { usePollingResource } from "../hooks/usePollingResource";
import { navigate } from "../router";
import type { WorkflowMetric } from "../types";

function Sparkline({ values, tone }: { values: number[]; tone: string }) {
  if (values.length <= 1) {
    return <span className="trend-unavailable" aria-label="Trend unavailable">—</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${24 - ((value - min) / range) * 20}`).join(" ");
  return <svg className={`sparkline sparkline--${tone}`} viewBox="0 0 100 28" preserveAspectRatio="none" aria-label="Execution trend for today"><polyline points={points} /></svg>;
}

function WorkflowHealthRow({ metric }: { metric: WorkflowMetric }) {
  return (
    <button className="workflow-health__row" onClick={() => navigate(`/executions?workflow=${encodeURIComponent(metric.workflow_key)}`)}>
      <strong>{metric.workflow}</strong>
      <StatusMark status={metric.status} />
      <span>{formatPercent(metric.success_rate)}</span>
      <Sparkline values={metric.trend} tone={metric.status} />
      <span>{metric.executions}</span>
      <span>{formatDuration(metric.average_latency_ms)}</span>
      <span>{metric.p95_latency_ms === undefined ? "—" : formatDuration(metric.p95_latency_ms)}</span>
      <Icon name="chevron" />
    </button>
  );
}

export function OverviewPage({ onRunDemo }: { onRunDemo: () => void }) {
  const resource = usePollingResource(async () => {
    const [metrics, executions] = await Promise.all([
      client.getMetrics(),
      client.getExecutions({ limit: 8 }),
    ]);
    const liveCandidate = executions.items.find((execution) => execution.status === "running" || execution.status === "waiting_for_review");
    if (liveCandidate) {
      const detail = await client.getExecution(liveCandidate.execution_id).catch(() => liveCandidate);
      executions.items = executions.items.map((execution) => execution.execution_id === liveCandidate.execution_id ? { ...execution, events: detail.events } : execution);
    }
    return { metrics, executions };
  }, [], 5_000);

  const liveExecution = useMemo(() => resource.data?.executions.items.find((execution) => execution.status === "running" || execution.status === "waiting_for_review"), [resource.data]);

  return (
    <div className="overview-page">
      <div className="overview-page__primary">
        <PageHeader title="Workflow operations" action={<Button variant="primary" className="mobile-run-demo" onClick={onRunDemo}><Icon name="play" /> Run demo</Button>} />
        {resource.error && !resource.data ? <ErrorBanner error={resource.error} onRetry={resource.reload} /> : null}
        {resource.data ? (
          <>
            <section className="metric-strip" aria-label="Operational metrics">
              <article><span>Executions today</span><strong>{resource.data.metrics.executions_today}</strong></article>
              <article><span>Success rate</span><strong>{formatPercent(resource.data.metrics.success_rate)}</strong></article>
              <article><span>Failure rate</span><strong className={resource.data.metrics.failure_rate > 5 ? "metric-danger" : ""}>{formatPercent(resource.data.metrics.failure_rate)}</strong></article>
              <article><span>Review rate</span><strong className="metric-warning">{formatPercent(resource.data.metrics.review_rate)}</strong></article>
              <article><span>Average latency</span><strong>{formatDuration(resource.data.metrics.average_latency_ms)}</strong></article>
              <article><span>P95 latency</span><strong>{formatDuration(resource.data.metrics.p95_latency_ms)}</strong></article>
            </section>

            <section className="operations-panel workflow-health">
              <SectionHeader title="Workflow health" meta="Today" action={<div className="health-legend"><span><i className="dot dot--success" />Healthy</span><span><i className="dot dot--warning" />Degraded</span><span><i className="dot dot--danger" />Unhealthy</span></div>} />
              <div className="workflow-health__table" role="table" aria-label="Workflow health metrics">
                <div className="workflow-health__header" role="row"><span>Workflow</span><span>Status</span><span>Success</span><span>Trend</span><span>Runs</span><span>Avg latency</span><span>P95 latency</span><span /></div>
                {resource.data.metrics.workflows.length ? resource.data.metrics.workflows.map((metric) => <WorkflowHealthRow key={metric.workflow_key} metric={metric} />) : <EmptyState title="No workflow metrics yet" body="Metrics appear here after a workflow has run." />}
              </div>
            </section>

            <section className="operations-panel recent-executions">
              <SectionHeader title="Recent executions" action={<Button variant="ghost" onClick={() => navigate("/executions")}>View all <Icon name="arrow" /></Button>} />
              {resource.data.executions.items.length ? (
                <div className="execution-table" role="table" aria-label="Recent executions">
                  <div className="execution-table__header" role="row"><span>Execution</span><span>Workflow</span><span>Correlation</span><span>Status</span><span>Decision</span><span>Started</span><span>Duration</span><span /></div>
                  {resource.data.executions.items.map((execution) => (
                    <button className={`execution-table__row${liveExecution?.execution_id === execution.execution_id ? " execution-table__row--selected" : ""}`} role="row" key={execution.execution_id} onClick={() => navigate(`/executions?execution=${encodeURIComponent(execution.execution_id)}`)}>
                      <span className="mono link-text">{execution.execution_id}</span><span>{execution.workflow}</span><span className="mono">{execution.correlation_id}</span><StatusMark status={execution.status} /><span>{execution.decision_summary}</span><span>{formatTime(execution.started_at, true)}</span><span>{formatDuration(execution.duration_ms)}</span><Icon name="chevron" />
                    </button>
                  ))}
                </div>
              ) : <EmptyState title="No executions yet" body="Run a demo scenario to create the first execution." icon="executions" />}
            </section>
          </>
        ) : !resource.error ? <><div className="metric-strip metric-strip--loading" /><LoadingRows count={8} /></> : null}
      </div>

      <aside className="live-activity" aria-label="Live activity">
        <SectionHeader title="Live activity" action={<span className="live-label"><i />Live</span>} />
        {resource.loading ? <LoadingRows count={6} /> : null}
        {liveExecution ? (
          <>
            <button className="live-activity__execution" onClick={() => navigate(`/executions?execution=${encodeURIComponent(liveExecution.execution_id)}`)}>
              <strong>{liveExecution.execution_id}</strong><span>{liveExecution.workflow}</span><small>Started {formatTime(liveExecution.started_at)}</small>
            </button>
            <Timeline events={liveExecution.events} compact />
            <Button variant="ghost" onClick={() => navigate(`/executions?execution=${encodeURIComponent(liveExecution.execution_id)}`)}>View full trace <Icon name="external" /></Button>
          </>
        ) : !resource.loading ? <EmptyState title="No live activity" body="New workflow stages will appear here." /> : null}
      </aside>
    </div>
  );
}
