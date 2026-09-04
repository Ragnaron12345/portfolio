import { useMemo, useState } from "react";
import { client } from "../api/client";
import { Icon } from "../components/Icon";
import {
  EmptyState,
  ErrorBanner,
  LoadingRows,
  PageHeader,
  RefreshMeta,
  StatusMark,
  formatTime,
  humanize,
} from "../components/Ui";
import { usePollingResource } from "../hooks/usePollingResource";
import { queryParam, setQueryParam } from "../router";

export function AuditLogPage() {
  const workflow = queryParam("workflow") ?? "";
  const outcome = queryParam("outcome") ?? "";
  const selectedId = queryParam("event");
  const [search, setSearch] = useState("");
  const resource = usePollingResource(() => client.getAuditEvents({ workflow, outcome, limit: 100 }), [workflow, outcome], 5_000);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (resource.data?.items ?? []).filter((event) => {
      const matchesWorkflow = !workflow || event.workflow.toLowerCase().includes(workflow);
      const normalizedOutcome = `${event.outcome} ${event.event_type}`.toLowerCase();
      const matchesOutcome = !outcome
        || (outcome === "success" && /success|completed|accepted|created|sent|submitted|deduplicated/.test(normalizedOutcome) && !/fail|error|reject|timeout|review|pending/.test(normalizedOutcome))
        || (outcome === "review" && /review|pending|approval/.test(normalizedOutcome))
        || (outcome === "failed" && /fail|error|reject|timeout/.test(normalizedOutcome));
      const matchesSearch = !query || [event.id, event.execution_id, event.correlation_id, event.workflow, event.action, event.reason, event.actor]
        .some((value) => value.toLowerCase().includes(query));
      return matchesWorkflow && matchesOutcome && matchesSearch;
    });
  }, [outcome, resource.data, search, workflow]);
  const selected = resource.data?.items.find((event) => event.id === selectedId);

  return (
    <div className="page audit-page">
      <PageHeader title="Audit log" subtitle="Immutable operational decisions, external actions and failure evidence." action={<RefreshMeta lastUpdated={resource.lastUpdated} refreshing={resource.refreshing} onRefresh={resource.reload} />} />
      <div className="audit-toolbar">
        <label className="search-control"><Icon name="search" /><span className="sr-only">Search audit events</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search execution, action or reason" /></label>
        <label><span className="sr-only">Filter by workflow</span><select value={workflow} onChange={(event) => setQueryParam("workflow", event.target.value || null)}><option value="">All workflows</option><option value="support">AI Support Triage</option><option value="invoice">Invoice Processing</option><option value="incident">Incident Intelligence</option></select></label>
        <label><span className="sr-only">Filter by outcome</span><select value={outcome} onChange={(event) => setQueryParam("outcome", event.target.value || null)}><option value="">All outcomes</option><option value="success">Success</option><option value="review">Review</option><option value="failed">Failed</option></select></label>
      </div>
      {resource.error && !resource.data ? <ErrorBanner error={resource.error} onRetry={resource.reload} /> : null}
      <div className={`audit-layout${selected ? " audit-layout--selected" : ""}`}>
        <section className="audit-surface">
          <div className="audit-surface__heading"><h2>Recorded events</h2><span>{filtered.length} of {resource.data?.total ?? 0}</span></div>
          {resource.loading ? <LoadingRows count={8} /> : null}
          {filtered.length ? (
            <div className="audit-table" role="table" aria-label="Audit events">
              <div className="audit-table__header" role="row"><span>Time</span><span>Execution</span><span>Workflow</span><span>Action</span><span>Actor</span><span>Outcome</span><span /></div>
              {filtered.map((event) => <button className={`audit-row${event.id === selectedId ? " audit-row--selected" : ""}`} role="row" key={event.id} onClick={() => setQueryParam("event", event.id)}><time dateTime={event.created_at}>{formatTime(event.created_at, true)}</time><code>{event.execution_id}</code><span>{event.workflow}</span><span><strong>{humanize(event.event_type)}</strong><small>{event.action}</small></span><span>{event.actor}</span><StatusMark status={event.outcome} /><Icon name="chevron" /></button>)}
            </div>
          ) : null}
          {!resource.loading && filtered.length === 0 ? <EmptyState title="No audit events found" body={search || workflow || outcome ? "Clear filters to see more operational history." : "Events appear after workflows begin processing."} icon="audit" /> : null}
        </section>
        {selected ? (
          <aside className="audit-detail" aria-label="Audit event detail">
            <header><div><span className="eyeline">Audit event</span><h2>{humanize(selected.event_type)}</h2></div><button className="icon-button" aria-label="Close audit detail" onClick={() => setQueryParam("event", null)}><Icon name="close" /></button></header>
            <StatusMark status={selected.outcome} />
            <dl>
              <div><dt>Event ID</dt><dd>{selected.id}</dd></div><div><dt>Execution</dt><dd>{selected.execution_id}</dd></div><div><dt>Correlation</dt><dd>{selected.correlation_id}</dd></div><div><dt>Workflow</dt><dd>{selected.workflow}</dd></div><div><dt>Actor</dt><dd>{selected.actor}</dd></div><div><dt>Recorded</dt><dd>{formatTime(selected.created_at, true)}</dd></div>
            </dl>
            <section><h3>Action</h3><p>{selected.action}</p></section>
            <section><h3>Reason</h3><p>{selected.reason || "No additional reason was recorded."}</p></section>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
