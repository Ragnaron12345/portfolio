import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { formatMetric } from "../lib/format";
import { navigate } from "../lib/router";
import type { FailureCase, FailureData, RunSummary } from "../types";
import { Icon } from "../components/Icon";
import { StatePanel } from "../components/StatePanel";
import { PageFrame, PageHeader } from "./OverviewPage";

export function FailureExplorerPage({ initialRunId }: { initialRunId: string | null }) {
  const query = new URLSearchParams(window.location.search);
  const regressionsOnly = query.get("regressions") === "1";
  const requestedCase = query.get("case");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState(initialRunId ?? "");
  const [data, setData] = useState<FailureData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(requestedCase);
  const [category, setCategory] = useState("");
  const [failureType, setFailureType] = useState("");
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [retrieval, setRetrieval] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<RunSummary[]>("/runs").then((items) => {
      setRuns(items);
      if (!initialRunId && items[0]) {
        setRunId(items[0].id);
        navigate(`/failures?runId=${items[0].id}${regressionsOnly ? "&regressions=1" : ""}`, true);
      }
    }).catch((reason: Error) => setError(reason.message));
  }, [initialRunId, regressionsOnly]);

  useEffect(() => {
    if (!runId) return;
    setData(null);
    api<FailureData>(`/runs/${runId}/failures?regressions_only=${regressionsOnly}`).then((payload) => {
      setData(payload);
      setSelectedId((current) => current && payload.items.some((item) => item.case_id === current) ? current : payload.items[0]?.case_id ?? null);
      setError(null);
    }).catch((reason: Error) => setError(reason.message));
  }, [regressionsOnly, runId]);

  const run = runs.find((item) => item.id === runId);
  const categories = useMemo(() => [...new Set(data?.items.map((item) => item.category) ?? [])], [data]);
  const failureTypes = useMemo(() => [...new Set(data?.items.flatMap((item) => item.failed_metrics) ?? [])], [data]);
  const filtered = useMemo(() => data?.items.filter((item) =>
    (!category || item.category === category) &&
    (!failureType || item.failed_metrics.includes(failureType)) &&
    (!model || item.model_config_id === model) &&
    (!prompt || item.prompt_version_id === prompt) &&
    (!retrieval || item.retrieval_config_id === retrieval),
  ) ?? [], [category, data, failureType, model, prompt, retrieval]);
  const selected = filtered.find((item) => item.case_id === selectedId) ?? filtered[0] ?? null;

  function changeRun(value: string) {
    setRunId(value);
    setSelectedId(null);
    navigate(`/failures?runId=${value}${regressionsOnly ? "&regressions=1" : ""}`);
  }

  if (error) return <PageFrame><StatePanel kind="error" title="Failure explorer unavailable">{error}</StatePanel></PageFrame>;
  if (!data || !run) return <PageFrame><StatePanel kind="loading" title="Loading failure evidence">Reading failed metrics, exact outputs and retry records…</StatePanel></PageFrame>;

  return (
    <PageFrame>
      <PageHeader title="Failure explorer" subtitle={regressionsOnly ? "Pairwise regressions only — aggregate gains remain visible in Run Detail" : "Inspect every failed metric, provider error and retry"} actions={<select value={runId} onChange={(event) => changeRun(event.target.value)} aria-label="Selected run">{runs.map((item) => <option key={item.id} value={item.id}>{item.experiment_name} · {item.id}</option>)}</select>} />
      <div className="classification-strip"><span><b>{data.pairwise_counts.improved}</b> improved</span><span><b>{data.pairwise_counts.unchanged}</b> unchanged</span><span className="danger"><b>{data.pairwise_counts.regressed}</b> regressed</span><button className={regressionsOnly ? "active" : ""} onClick={() => navigate(`/failures?runId=${runId}${regressionsOnly ? "" : "&regressions=1"}`)}>{regressionsOnly ? "Show all failures" : "Regressions only"}</button></div>
      <div className="filter-bar" aria-label="Failure filters">
        <label>Model<select value={model} onChange={(event) => setModel(event.target.value)}><option value="">All models</option>{run.config_snapshot.models.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Prompt<select value={prompt} onChange={(event) => setPrompt(event.target.value)}><option value="">All prompts</option>{run.config_snapshot.prompts.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.semantic_version}</option>)}</select></label>
        <label>Retrieval<select value={retrieval} onChange={(event) => setRetrieval(event.target.value)}><option value="">All configs</option>{run.config_snapshot.retrieval_configs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{categories.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>
        <label>Failure type<select value={failureType} onChange={(event) => setFailureType(event.target.value)}><option value="">All failures</option>{failureTypes.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>
      </div>
      {!filtered.length ? <StatePanel kind="empty" title="No failures match these filters">The run and filters remain selected; broaden a filter to continue.</StatePanel> : <div className="failure-layout">
        <section className="failure-list">
          <header><span>{filtered.length} results</span><strong>{regressionsOnly ? "Regressions" : "Failures"}</strong></header>
          {filtered.map((item) => <button key={item.id} className={selected?.id === item.id ? "failure-row selected" : "failure-row"} onClick={() => setSelectedId(item.case_id)}><span><strong>{item.case_id}</strong><em>{item.classification ?? item.status}</em></span><b>{item.category.replaceAll("_", " ")}</b><small>{item.failed_metrics.map((name) => name.replaceAll("_", " ")).join(" · ") || "quality score decreased"}</small><Icon name="chevron" /></button>)}
        </section>
        {selected ? <FailureInspector item={selected} run={run} /> : null}
      </div>}
    </PageFrame>
  );
}

function FailureInspector({ item, run }: { item: FailureCase; run: RunSummary }) {
  const combination = run.config_snapshot.combinations.find((candidate) => candidate.key === item.combination_key);
  return <article className="failure-inspector">
    <header><div><span>{item.case_id}</span><h2>{item.category.replaceAll("_", " ")}</h2></div><em className={item.classification === "regressed" ? "danger-label" : "neutral-label"}>{item.classification ?? item.status}</em></header>
    <dl className="case-stats"><div><dt>Configuration</dt><dd>{combination?.label ?? item.combination_key}</dd></div><div><dt>Latency</dt><dd>{item.latency_ms === null ? "unavailable" : `${item.latency_ms.toFixed(1)} ms`}</dd></div><div><dt>Cost</dt><dd>{item.cost_usd === null ? "unavailable" : `$${item.cost_usd.toFixed(6)}`}</dd></div><div><dt>Retries</dt><dd>{item.retry_count}</dd></div></dl>
    {item.error_message ? <div className="error-evidence"><strong>{item.error_type}</strong><code>{item.error_message}</code></div> : null}
    <EvidenceBlock title="Input"><p>{item.input}</p></EvidenceBlock>
    <EvidenceBlock title="Reference answer"><pre>{item.reference_answer ?? "No reference answer — keyword and safety metrics apply."}</pre></EvidenceBlock>
    <EvidenceBlock title="Context">{item.context.length ? item.context.map((value) => <pre key={value}>{value}</pre>) : <p>No context supplied.</p>}</EvidenceBlock>
    <EvidenceBlock title="Model output"><pre>{item.output ?? "No output was returned."}</pre></EvidenceBlock>
    <EvidenceBlock title="Failed metrics"><div className="metric-evidence">{item.metrics.filter((metric) => item.failed_metrics.includes(metric.name)).map((metric) => <div key={metric.name}><strong>{metric.label}</strong><b>{formatMetric(metric.value, metric.unit)}</b><span>{metric.definition}</span><small>{metric.better_direction} is better · n=1</small></div>)}</div></EvidenceBlock>
    {item.judge ? <EvidenceBlock title="Judge notes"><pre>{JSON.stringify(item.judge, null, 2)}</pre></EvidenceBlock> : null}
    {item.retrieved_chunks.length ? <EvidenceBlock title="Retrieved chunks"><div className="chunk-list compact-chunks">{item.retrieved_chunks.map((chunk) => <div key={`${chunk.rank}-${chunk.source_id}`}><span>#{chunk.rank}</span><strong>{chunk.source_id}</strong><b>{chunk.score.toFixed(3)}</b><em>{chunk.expected_source ? "expected-source hit" : "not expected"}</em><p>{chunk.text}</p></div>)}</div></EvidenceBlock> : null}
  </article>;
}

function EvidenceBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="evidence-block"><h3>{title}</h3>{children}</section>;
}
