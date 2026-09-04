import { useEffect } from "react";
import { client } from "../api/client";
import { ExecutionDetail } from "../components/ExecutionDetail";
import { Icon } from "../components/Icon";
import { Timeline } from "../components/Timeline";
import {
  Button,
  EmptyState,
  ErrorBanner,
  LoadingRows,
  PageHeader,
  RefreshMeta,
  StatusMark,
  formatDuration,
  formatPercent,
  formatTime,
} from "../components/Ui";
import { usePollingResource } from "../hooks/usePollingResource";
import { queryParam, setQueryParam, setQueryParams } from "../router";
import type { Execution } from "../types";

function MobileExecutionSummary({ execution }: { execution: Execution }) {
  return (
    <div className="mobile-execution-summary">
      <dl>
        <div><dt>Decision</dt><dd>{execution.decision_summary}</dd></div>
        <div><dt>Correlation</dt><dd>{execution.correlation_id}</dd></div>
        <div><dt>Duration</dt><dd>{formatDuration(execution.duration_ms)}</dd></div>
        <div><dt>Workflow</dt><dd>{execution.workflow}</dd></div>
        <div><dt>Status</dt><dd><StatusMark status={execution.status} /></dd></div>
      </dl>
      <h3>Live timeline</h3>
      <Timeline events={execution.events} compact />
      <a href="#execution-detail" className="mobile-detail-link">View workflow evidence <Icon name="arrow" /></a>
    </div>
  );
}

function ExecutionListItem({ execution, selected, onSelect }: { execution: Execution; selected: boolean; onSelect: () => void }) {
  return (
    <div className={`execution-list-item${selected ? " execution-list-item--selected" : ""}`}>
      <button className="execution-list-item__button" onClick={onSelect} aria-expanded={selected}>
        <span className="mono link-text">{execution.execution_id}</span>
        <span>{execution.workflow}</span>
        <StatusMark status={execution.status} />
        <span className="execution-list-item__started">{formatTime(execution.started_at, true)}</span>
        <Icon name="chevron" />
      </button>
      {selected ? <MobileExecutionSummary execution={execution} /> : null}
    </div>
  );
}

export function ExecutionsPage({ onRunDemo }: { onRunDemo: () => void }) {
  const selectedId = queryParam("execution");
  const workflow = queryParam("workflow") ?? "";
  const list = usePollingResource(async () => {
    const [executions, metrics] = await Promise.all([
      client.getExecutions({ workflow, limit: 50 }),
      client.getMetrics(),
    ]);
    return { executions, metrics };
  }, [workflow], 5_000);

  useEffect(() => {
    const firstMatching = list.data?.executions.items.find((execution) => !workflow || execution.workflow_key === workflow);
    if (!selectedId && firstMatching) {
      setQueryParam("execution", firstMatching.execution_id, true);
    }
  }, [list.data, selectedId, workflow]);

  const selected = usePollingResource(async () => {
    if (!selectedId) throw new Error("Select an execution to inspect its trace.");
    const execution = await client.getExecution(selectedId);
    const events = await client.getExecutionEvents(selectedId).catch(() => execution.events);
    return { ...execution, events: execution.events.length ? execution.events : events };
  }, [selectedId], selectedId ? 5_000 : 0);

  const listSelected = list.data?.executions.items.find((execution) => execution.execution_id === selectedId);
  const mobileSelected = selected.data ?? listSelected;

  return (
    <div className="page executions-page">
      <PageHeader
        title="Executions"
        action={<Button variant="primary" onClick={onRunDemo}><Icon name="play" /> Run demo</Button>}
      />

      <div className="executions-toolbar">
        <label>
          <span className="sr-only">Filter by workflow</span>
          <select value={workflow} onChange={(event) => setQueryParams({ workflow: event.target.value || null, execution: null })}>
            <option value="">All workflows</option>
            <option value="support">AI Support Triage</option>
            <option value="invoice">Invoice Processing</option>
            <option value="incident">Incident Intelligence</option>
          </select>
        </label>
        <RefreshMeta lastUpdated={list.lastUpdated} refreshing={list.refreshing || selected.refreshing} onRefresh={() => { list.reload(); selected.reload(); }} />
      </div>

      {list.data ? (
        <section className="mobile-metric-strip" aria-label="Execution metrics">
          <article><span>Today</span><strong>{list.data.metrics.executions_today}</strong></article>
          <article><span>Success</span><strong className="success-text">{formatPercent(list.data.metrics.success_rate)}</strong></article>
          <article><span>Reviews</span><strong className="warning-text">{formatPercent(list.data.metrics.review_rate)}</strong></article>
        </section>
      ) : null}

      {list.error && !list.data ? <ErrorBanner error={list.error} onRetry={list.reload} /> : null}
      <div className="executions-layout">
        <section className="execution-list-panel" aria-label="Execution list">
          <div className="execution-list-panel__header"><h2>Recent executions</h2>{list.data ? <span>{list.data.executions.total} results</span> : null}</div>
          {list.loading ? <LoadingRows count={7} /> : null}
          {list.data?.executions.items.length ? list.data.executions.items.map((execution) => (
            <ExecutionListItem
              key={execution.execution_id}
              execution={execution.execution_id === selectedId && mobileSelected ? mobileSelected : execution}
              selected={execution.execution_id === selectedId}
              onSelect={() => setQueryParam("execution", execution.execution_id)}
            />
          )) : null}
          {!list.loading && list.data?.executions.items.length === 0 ? <EmptyState title="No executions found" body="Run a demo or choose another workflow filter." icon="executions" /> : null}
        </section>

        <section className="execution-detail-panel" id="execution-detail" aria-label="Selected execution detail">
          {selected.loading && selectedId ? <LoadingRows count={9} /> : null}
          {selected.error && selectedId ? <ErrorBanner error={selected.error} onRetry={selected.reload} /> : null}
          {selected.data ? <ExecutionDetail execution={selected.data} /> : null}
          {!selectedId && !selected.loading ? <EmptyState title="Select an execution" body="Choose a row to inspect decisions, evidence, retries, actions and the full timeline." icon="executions" /> : null}
        </section>
      </div>
    </div>
  );
}
