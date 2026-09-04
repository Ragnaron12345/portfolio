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
} from "../components/Ui";
import { usePollingResource } from "../hooks/usePollingResource";
import { queryParam, setQueryParam } from "../router";
import type { MockSystemKey } from "../types";

const systems: Array<{ key: MockSystemKey; name: string; product: string; description: string; icon: "reviews" | "warning" | "executions" | "file" }> = [
  { key: "tickets", name: "CRM tickets", product: "Mock CRM", description: "Customer-facing support actions created by approved triage runs.", icon: "reviews" },
  { key: "incidents", name: "Jira incidents", product: "Mock Jira", description: "Incident records and deduplicated monitoring updates.", icon: "warning" },
  { key: "messages", name: "Slack messages", product: "Mock Slack", description: "Operational notifications emitted by incident workflows.", icon: "executions" },
  { key: "invoices", name: "ERP invoices", product: "Mock ERP", description: "Validated invoices submitted exactly once after deterministic checks.", icon: "file" },
];

function isSystem(value: string | null): value is MockSystemKey {
  return systems.some((system) => system.key === value);
}

export function MockSystemsPage() {
  const rawSystem = queryParam("system");
  const active = isSystem(rawSystem) ? rawSystem : "tickets";
  const system = systems.find((item) => item.key === active) ?? systems[0]!;
  const resource = usePollingResource(() => client.getMockRecords(active), [active], 5_000);

  return (
    <div className="page systems-page">
      <PageHeader title="Mock systems" subtitle="Local integrations make every workflow demonstrable without paid SaaS." action={<RefreshMeta lastUpdated={resource.lastUpdated} refreshing={resource.refreshing} onRefresh={resource.reload} />} />
      <div className="local-environment-banner"><span className="live-dot" /><div><strong>Local demo environment</strong><p>These records are persisted by the backend and include the originating execution ID.</p></div></div>
      <div className="systems-tabs" role="tablist" aria-label="Mock external systems">
        {systems.map((item) => <button key={item.key} role="tab" aria-selected={active === item.key} className={active === item.key ? "is-active" : ""} onClick={() => setQueryParam("system", item.key)}><Icon name={item.icon} /><span>{item.name}</span></button>)}
      </div>
      <section className="system-surface" role="tabpanel">
        <header className="system-surface__header">
          <div><span className="system-logo"><Icon name={system.icon} /></span><div><span className="eyeline">{system.product}</span><h2>{system.name}</h2><p>{system.description}</p></div></div>
          <strong>{resource.data?.total ?? 0}<span>records</span></strong>
        </header>
        {resource.error && !resource.data ? <ErrorBanner error={resource.error} onRetry={resource.reload} /> : null}
        {resource.loading ? <LoadingRows count={6} /> : null}
        {resource.data?.items.length ? (
          <div className="mock-record-table" role="table" aria-label={system.name}>
            <div className="mock-record-table__header" role="row"><span>ID</span><span>Record</span><span>Execution</span><span>Status</span><span>Created</span></div>
            {resource.data.items.map((record) => (
              <article className="mock-record" role="row" key={record.id}>
                <code>{record.id}</code>
                <div><strong>{record.title}</strong>{record.fields.length ? <dl>{record.fields.map((field) => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl> : null}</div>
                <code>{record.execution_id}</code>
                <StatusMark status={record.status} />
                <time dateTime={record.created_at}>{formatTime(record.created_at, true)}</time>
              </article>
            ))}
          </div>
        ) : null}
        {!resource.loading && resource.data?.items.length === 0 ? <EmptyState title={`No ${system.name.toLowerCase()} yet`} body="Run a matching demo scenario to exercise this integration." icon="systems" /> : null}
      </section>
    </div>
  );
}
