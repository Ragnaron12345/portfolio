import { useCallback, useEffect, useState } from "react";
import { client } from "../api/client";
import { navigate } from "../components/AppShell";
import { Button, EmptyState, ErrorBanner, LoadingRows, PageHeader, StatusMark, formatDuration, formatMoney, formatNumber, formatPercent } from "../components/Ui";
import type { AvailableModel, MetricsSummary, ModelMetric, ReviewItem } from "../types";

const EMPTY_METRICS: MetricsSummary = {
  total_requests: 0,
  success_rate: 0,
  escalation_rate: 0,
  average_latency_ms: 0,
  p95_latency_ms: 0,
  total_tokens: 0,
  estimated_spend: 0,
  error_rate: 0,
  retrieval_hit_rate: 0,
  pending_reviews: 0,
};

function MetricStrip({ metrics }: { metrics: MetricsSummary }) {
  const items = [
    ["Total requests", formatNumber(metrics.total_requests), `${formatNumber(metrics.total_tokens)} tokens`],
    ["Success rate", formatPercent(metrics.success_rate), `${formatPercent(metrics.error_rate)} error rate`],
    ["Escalation rate", formatPercent(metrics.escalation_rate), `${metrics.pending_reviews} pending reviews`],
    ["P95 latency", formatDuration(metrics.p95_latency_ms), `${formatDuration(metrics.average_latency_ms)} average`],
    ["Estimated spend", formatMoney(metrics.estimated_spend), `${formatPercent(metrics.retrieval_hit_rate)} retrieval hit`],
  ];
  return (
    <section className="metric-strip" aria-label="Operations metrics">
      {items.map(([label, value, detail]) => (
        <div className="metric-strip__item" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          <small>{detail}</small>
        </div>
      ))}
    </section>
  );
}

function VolumeChart({ data }: { data: NonNullable<MetricsSummary["timeline"]> }) {
  if (data.length === 0) {
    return <EmptyState title="No request activity yet" message="Submit requests to build an observable traffic timeline." />;
  }
  const width = 760;
  const height = 280;
  const left = 58;
  const right = 76;
  const top = 24;
  const bottom = 44;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  let maxRequests = 1;
  let maxLatency = 1;
  for (const point of data) {
    maxRequests = Math.max(maxRequests, point.requests);
    maxLatency = Math.max(maxLatency, point.latency_ms);
  }
  const requestCeiling = maxRequests <= 4 ? 4 : Math.ceil(maxRequests / 4) * 4;
  const latencyCeiling = maxLatency;
  const toPoints = (key: "requests" | "latency_ms", maximum: number) =>
    data.map((point, index) => {
      const x = data.length === 1 ? left + plotWidth / 2 : left + (index * plotWidth) / (data.length - 1);
      const y = top + plotHeight - (point[key] / maximum) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");

  const marker = (key: "requests" | "latency_ms", maximum: number, className: string) =>
    data.map((point, index) => {
      const x = data.length === 1 ? left + plotWidth / 2 : left + (index * plotWidth) / (data.length - 1);
      const y = top + plotHeight - (point[key] / maximum) * plotHeight;
      return <circle key={`${key}-${point.bucket}`} cx={x} cy={y} r="4" className={className}><title>{point.bucket}: {key === "requests" ? `${point.requests} requests` : `${formatDuration(point.latency_ms)} average latency`}</title></circle>;
    });

  const latest = data.at(-1)!;
  const xLabelEvery = Math.max(1, Math.ceil(data.length / 6));
  const axisRatios = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="chart-wrap">
      <div className="chart-legend"><span>Left axis</span><span className="legend-line legend-line--blue" />Requests <span>Right axis</span><span className="legend-line legend-line--orange" />Avg latency</div>
      <div className="chart-readout"><div><span>Latest volume</span><strong>{formatNumber(latest.requests)}</strong><small>{latest.bucket}</small></div><div><span>Latest latency</span><strong>{formatDuration(latest.latency_ms)}</strong><small>average lifecycle</small></div><div><span>Peak volume</span><strong>{formatNumber(maxRequests)}</strong><small>in displayed window</small></div></div>
      <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Request volume and average latency over ${data.length} time buckets. Latest: ${latest.requests} requests at ${formatDuration(latest.latency_ms)}.`}>
        <text x={left} y="12" className="chart-axis-title chart-axis-title--requests">REQUESTS</text>
        <text x={width - right} y="12" textAnchor="end" className="chart-axis-title chart-axis-title--latency">AVG LATENCY</text>
        {axisRatios.map((ratio) => {
          const y = top + plotHeight - ratio * plotHeight;
          return <g key={ratio}><line x1={left} x2={width - right} y1={y} y2={y} className="chart-grid" /><text x={left - 10} y={y + 4} textAnchor="end" className="chart-tick chart-tick--requests">{formatNumber(requestCeiling * ratio)}</text><text x={width - right + 10} y={y + 4} className="chart-tick chart-tick--latency">{formatDuration(latencyCeiling * ratio)}</text></g>;
        })}
        <polyline points={toPoints("requests", requestCeiling)} className="chart-line chart-line--requests" />
        <polyline points={toPoints("latency_ms", latencyCeiling)} className="chart-line chart-line--latency" />
        {marker("requests", requestCeiling, "chart-marker chart-marker--requests")}
        {marker("latency_ms", latencyCeiling, "chart-marker chart-marker--latency")}
        {data.map((point, index) => {
          if (index % xLabelEvery !== 0 && index !== data.length - 1) return null;
          const x = data.length === 1 ? left + plotWidth / 2 : left + (index * plotWidth) / (data.length - 1);
          return <text key={point.bucket} x={x} y={height - 13} textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"} className="chart-tick chart-tick--x">{point.bucket}</text>;
        })}
      </svg>
    </div>
  );
}

function riskTone(risk?: string) {
  if (risk === "high") return "danger" as const;
  if (risk === "medium") return "warning" as const;
  return "neutral" as const;
}

function modelShare(model: ModelMetric, totalCalls: number) {
  if (model.percentage !== undefined) return model.percentage > 1 ? model.percentage / 100 : model.percentage;
  return totalCalls ? model.requests / totalCalls : 0;
}

export function OverviewPage() {
  const [metrics, setMetrics] = useState<MetricsSummary>(EMPTY_METRICS);
  const [models, setModels] = useState<ModelMetric[]>([]);
  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [modelDiscoveryFailed, setModelDiscoveryFailed] = useState(false);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [metricData, modelData, reviewData] = await Promise.all([
        client.getMetrics(),
        client.getModelMetrics(),
        client.getReviews(),
      ]);
      setMetrics(metricData);
      setModels(modelData);
      setReviews(reviewData.filter((review) => ["pending", "decision_failed"].includes(review.status) || review.status.includes("in_progress")));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load operations data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    let cancelled = false;
    void client.getModels().then((configured) => {
      const eligible = configured.filter((model) => model.enabled !== false && !model.fallback_only);
      if (!cancelled) {
        setAvailableModels(eligible);
        setModelDiscoveryFailed(false);
      }
    }).catch(() => { if (!cancelled) { setAvailableModels([]); setModelDiscoveryFailed(true); } });
    return () => { cancelled = true; };
  }, []);

  const totalModelCalls = models.reduce((sum, model) => sum + model.requests, 0);
  const totalModelTokens = models.reduce((sum, model) => sum + model.tokens_in + model.tokens_out, 0);
  const totalModelCost = models.reduce((sum, model) => sum + model.cost, 0);

  return (
    <main className="page page--overview">
      <PageHeader
        title="Operations overview"
        actions={<Button variant="primary" icon="plus" onClick={() => navigate("/console")}>New request</Button>}
      />
      {error ? <ErrorBanner message={error} retry={() => void load()} /> : null}
      {loading ? <LoadingRows rows={3} /> : <MetricStrip metrics={metrics} />}
      <div className="overview-grid">
        <section className="panel panel--chart">
          <div className="section-heading"><h2>Request volume &amp; latency</h2><span>Latest window</span></div>
          {loading ? <LoadingRows rows={4} /> : <VolumeChart data={metrics.timeline ?? []} />}
        </section>
        <section className="panel panel--traces">
          <div className="section-heading"><h2>Live trace timeline</h2><button className="text-action" onClick={() => navigate("/console")}>Open console</button></div>
          {loading ? <LoadingRows rows={6} /> : metrics.recent_traces?.length ? (
            <ol className="trace-list">
              {metrics.recent_traces.slice(0, 7).map((trace) => (
                <li key={trace.trace_id} className={`trace-list__item trace-list__item--${trace.status}`}>
                  <span className="trace-node" />
                  <time>{new Date(trace.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
                  <code>{trace.trace_id.slice(0, 12)}</code>
                  <StatusMark tone={trace.status === "completed" || trace.status === "success" ? "success" : trace.status.includes("review") ? "warning" : "danger"}>{trace.status}</StatusMark>
                  <span>{formatDuration(trace.latency_ms)}</span>
                </li>
              ))}
            </ol>
          ) : <EmptyState title="No live traces" message="New request traces will appear here." />}
        </section>
        <section className="panel panel--models">
          <div className="section-heading"><h2>Model routing &amp; cost</h2><span>{availableModels.length} configured · {formatNumber(totalModelCalls)} persisted calls</span></div>
          <div className="model-portfolio" aria-label="Configured routing portfolio">
            {availableModels.length ? availableModels.map((model, index) => (
              <div key={`${model.provider}:${model.model}`}>
                <span className="model-portfolio__index">0{index + 1}</span>
                <strong>{model.display_name ?? model.model}</strong>
                <small>{model.role ?? "Configured model route"}{model.availability === "configured_unverified" ? " · live catalog unverified" : ""}{model.pricing_source ? ` · ${model.pricing_source}` : ""}</small>
                <code>{model.input_cost_per_million || model.output_cost_per_million ? `${formatMoney(model.input_cost_per_million ?? 0)} in · ${formatMoney(model.output_cost_per_million ?? 0)} out / 1M` : model.provider}</code>
              </div>
            )) : <EmptyState title={modelDiscoveryFailed ? "Model discovery unavailable" : "No remote models enabled"} message={modelDiscoveryFailed ? "Nexora could not verify the provider registry, so it will not present expected models as configured." : "This runtime exposes only the deterministic fallback. Add a provider key and enable its model routes to populate the portfolio."} />}
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Provider</th><th>Model</th><th>Calls</th><th>Distribution</th><th>Tokens in / out</th><th>Cost</th><th>Avg latency</th></tr></thead>
              <tbody>
                {models.length ? models.map((model) => (
                  <tr key={`${model.provider}:${model.model}`}>
                    <td>{model.provider}</td><td><code>{model.model}</code></td><td>{formatNumber(model.requests)}</td>
                    <td><span className="model-share"><i><b style={{ width: `${modelShare(model, totalModelCalls) * 100}%` }} /></i><code>{formatPercent(modelShare(model, totalModelCalls))}</code></span></td>
                    <td>{formatNumber(model.tokens_in)} / {formatNumber(model.tokens_out)}</td><td>{formatMoney(model.cost)}</td><td>{formatDuration(model.average_latency_ms)}</td>
                  </tr>
                )) : <tr><td colSpan={7} className="table-empty">No model calls recorded yet. The configured portfolio above is ready for routing.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="cost-explanation">
            <strong>{totalModelCost === 0 ? "Why is spend $0?" : `${formatMoney(totalModelCost)} across ${formatNumber(totalModelTokens)} tokens`}</strong>
            <p>{totalModelCost === 0 ? "No billable cost was recorded in this window. Attempts may be deterministic mock calls, remote calls that failed before billable usage, or calls whose configured rate is zero; inspect provider attempts and pricing provenance before treating $0 as an invoice." : "Spend is calculated per persisted provider attempt: input tokens × input rate / 1M, plus output tokens × output rate / 1M. Displayed totals are estimates, not an invoice."}</p>
          </div>
        </section>
        <section className="panel panel--reviews">
          <div className="section-heading"><h2>Review queue</h2><button className="text-action" onClick={() => navigate("/reviews")}>View all</button></div>
          <div className="review-preview">
            {reviews.length ? reviews.slice(0, 5).map((review) => (
              <button key={review.id} className="review-preview__row" onClick={() => navigate("/reviews")}>
                <span><strong>{review.reason}</strong><code>{review.request_id.slice(0, 12)}</code></span>
                <StatusMark tone={riskTone(review.risk_level ?? review.request?.risk_level)}>{review.risk_level ?? review.request?.risk_level ?? "review"}</StatusMark>
                <span>{Math.round((review.confidence ?? review.request?.confidence ?? 0) * 100)}%</span>
              </button>
            )) : <EmptyState title="Queue clear" message="Escalated requests will appear here." />}
          </div>
        </section>
      </div>
    </main>
  );
}
