import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { client } from "../api/client";
import { Button, EmptyState, ErrorBanner, LoadingRows, PageHeader, StatusMark, formatDuration, formatMoney, formatPercent } from "../components/Ui";
import type { EvaluationMetricSet, EvaluationResult, EvaluationRun } from "../types";

type MetricKind = "percent" | "duration" | "money";

interface MetricDefinition {
  key: keyof EvaluationMetricSet;
  label: string;
  definition: string;
  format: (value: number) => string;
  kind: MetricKind;
  lower?: boolean;
}

interface CaseIdentity {
  caseId: string;
  configuration: string;
}

interface DatasetSnapshot {
  name: string;
  version: string;
  caseCount: number;
  sha256?: string;
  source?: string;
}

const NEW_RUN_DATASET: DatasetSnapshot = {
  name: "Fintech support",
  version: "v1",
  caseCount: 40,
  source: "repository",
};
const NEW_RUN_CONFIGURATIONS = 2;

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function datasetSnapshot(run: EvaluationRun | null): DatasetSnapshot {
  if (!run) return NEW_RUN_DATASET;
  const config = record(run.config);
  const dataset = record(config.dataset);
  const perConfigurationCases = new Set((run.results ?? []).map((result) => result.case_id)).size;
  const caseCountValue = dataset.case_count ?? config.case_count;
  return {
    name: dataset.name ? String(dataset.name) : "Legacy evaluation snapshot",
    version: dataset.version ? String(dataset.version) : "unversioned",
    caseCount: typeof caseCountValue === "number" ? caseCountValue : perConfigurationCases,
    sha256: dataset.sha256 ? String(dataset.sha256) : undefined,
    source: dataset.source ? String(dataset.source) : undefined,
  };
}

function configurationProfile(run: EvaluationRun | null, name: string, legacyFallback: string) {
  const profiles = record(record(run?.config).configuration_profiles);
  const profile = record(profiles[name]);
  if (!Object.keys(profile).length) return { label: `${name.replace(/\b\w/g, (letter) => letter.toUpperCase())} pipeline`, detail: legacyFallback };
  const retrieval = profile.retrieval ? String(profile.retrieval) : "not recorded";
  const queryExpansion = profile.query_expansion === true ? "enabled" : profile.query_expansion === false ? "disabled" : "not recorded";
  const toolRetrieval = profile.opportunistic_tool_retrieval === true ? "enabled" : profile.opportunistic_tool_retrieval === false ? "disabled" : "not recorded";
  const purpose = profile.purpose ? ` ${String(profile.purpose)}` : "";
  return {
    label: profile.label ? String(profile.label) : `${name.replace(/\b\w/g, (letter) => letter.toUpperCase())} pipeline`,
    detail: `Retrieval: ${retrieval}. Query expansion: ${queryExpansion}. Opportunistic evidence retrieval for tool requests: ${toolRetrieval}.${purpose}`,
  };
}

const METRICS: MetricDefinition[] = [
  { key: "pass_rate", label: "Case pass rate", definition: "Share of cases that passed every required gate: intent, escalation, content, source recall, citations, grounding, structure, technical success, tool policy, and safety.", format: formatPercent, kind: "percent" },
  { key: "intent_accuracy", label: "Intent accuracy", definition: "Share of cases where the classified request intent exactly matches the expected intent.", format: formatPercent, kind: "percent" },
  { key: "retrieval_recall", label: "Source recall@K", definition: "Average share of expected sources found among the retrieved evidence for source-bearing cases.", format: formatPercent, kind: "percent" },
  { key: "retrieval_hit_rate", label: "Retrieval hit rate", definition: "Share of source-bearing cases where at least one expected source was retrieved.", format: formatPercent, kind: "percent" },
  { key: "citation_correctness", label: "Citation validity", definition: "Share of returned citations with the required document, chunk, title, source, and chunk-index structure.", format: formatPercent, kind: "percent" },
  { key: "groundedness", label: "Groundedness", definition: "Share of answer claims expected by the case that are supported by the complete cited chunks or recorded tool results.", format: formatPercent, kind: "percent" },
  { key: "escalation_correctness", label: "Escalation accuracy", definition: "Share of cases where the decision to require—or avoid—human review matches the expected decision.", format: formatPercent, kind: "percent" },
  { key: "structured_output_validity", label: "Structured output validity", definition: "Share of model responses that passed the pipeline's structured-output validation.", format: formatPercent, kind: "percent" },
  { key: "tool_policy_accuracy", label: "Tool-policy accuracy", definition: "Share of cases where the exact allowlisted tool set used by the pipeline matches the expected set.", format: formatPercent, kind: "percent" },
  { key: "failure_rate", label: "Technical failure rate", definition: "Share of cases that failed because the request pipeline or provider did not complete successfully. Lower is better.", format: formatPercent, kind: "percent", lower: true },
  { key: "p95_latency_ms", label: "P95 latency", definition: "Nearest-rank 95th-percentile evaluator wall-clock time. Ninety-five percent of cases completed at or below this value. Lower is better.", format: formatDuration, kind: "duration", lower: true },
  { key: "estimated_cost", label: "Estimated cost", definition: "Sum of recorded provider-call cost across this configuration. Deterministic local mock calls are not billable and therefore record $0. Lower is better.", format: formatMoney, kind: "money", lower: true },
];

function metricValue(metrics: EvaluationMetricSet | undefined, key: keyof EvaluationMetricSet) {
  return metrics?.[key];
}

function resultIdentity(result: EvaluationResult): CaseIdentity {
  return { caseId: result.case_id, configuration: result.configuration ?? "improved" };
}

function sameIdentity(result: EvaluationResult, identity: CaseIdentity | null) {
  return Boolean(identity && result.case_id === identity.caseId && (result.configuration ?? "improved") === identity.configuration);
}

function deltaLabel(current: number | undefined, baseline: number | undefined, metric: MetricDefinition) {
  if (current === undefined || baseline === undefined) return { text: "—", tone: "neutral" as const };
  const delta = current - baseline;
  const threshold = metric.kind === "money" ? 0.00000001 : 0.0001;
  if (Math.abs(delta) < threshold) return { text: "No change", tone: "neutral" as const };
  const improved = metric.lower ? delta < 0 : delta > 0;
  let text: string;
  if (metric.kind === "percent") text = `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)} pp`;
  else if (metric.kind === "duration") {
    const absolute = Math.abs(delta);
    text = `${delta > 0 ? "+" : "−"}${absolute < 10 ? absolute.toFixed(2) : Math.round(absolute)} ms`;
  }
  else text = `${delta > 0 ? "+" : "−"}${formatMoney(Math.abs(delta))}`;
  return { text, tone: improved ? "positive" as const : "negative" as const };
}

function InfoTip({ label, children }: { label: string; children: string }) {
  return (
    <span className="eval-tooltip">
      <button type="button" aria-label={`${label}: ${children}`}>?</button>
      <span role="tooltip">{children}</span>
    </span>
  );
}

function shortHash(value: unknown) {
  return value ? `${String(value).slice(0, 16)}…` : "—";
}

function hasComparableProvenance(run: EvaluationRun | null) {
  const config = record(run?.config);
  const hashes = [
    config.request_fingerprint,
    record(config.dataset).sha256,
    record(config.evaluator).sha256,
    record(config.pipeline).sha256,
    record(config.knowledge_snapshot).sha256,
  ];
  return hashes.every((value) => typeof value === "string" && value.length >= 16);
}

function EvaluationProvenance({ run }: { run: EvaluationRun }) {
  const config = record(run.config);
  const dataset = record(config.dataset);
  const evaluator = record(config.evaluator);
  const pipeline = record(config.pipeline);
  const knowledge = record(config.knowledge_snapshot);
  const runtime = record(config.runtime_settings);
  const models = Array.isArray(config.model_registry) ? config.model_registry.map((item) => record(item)) : [];
  const modelNames = models.map((model) => String(model.model ?? "unknown")).join(" · ") || "Not recorded";
  return <details className="eval-provenance"><summary><span>Provenance</span><strong>Verify the exact dataset, code, corpus, embeddings and route</strong><code>{shortHash(config.request_fingerprint)}</code></summary><dl><div><dt>Run fingerprint</dt><dd><code>{String(config.request_fingerprint ?? "Not recorded for this legacy run")}</code></dd></div><div><dt>Dataset</dt><dd>{String(dataset.name ?? "Legacy dataset")} {String(dataset.version ?? "")} · <code>{shortHash(dataset.sha256)}</code></dd></div><div><dt>Evaluator</dt><dd>{String(evaluator.version ?? "unversioned")} · <code>{shortHash(evaluator.sha256)}</code></dd></div><div><dt>Pipeline code</dt><dd><code>{shortHash(pipeline.sha256)}</code></dd></div><div><dt>Knowledge snapshot</dt><dd>{String(knowledge.document_count ?? "—")} documents · {String(knowledge.chunk_count ?? knowledge.declared_chunk_count ?? "—")} chunks · <code>{shortHash(knowledge.sha256)}</code></dd></div><div><dt>Embeddings</dt><dd>{String(runtime.embedding_provider ?? "—")} · {String(runtime.embedding_model ?? "—")} · {String(runtime.embedding_dimensions ?? "—")} dimensions{runtime.embedding_base_url ? ` · ${String(runtime.embedding_base_url)}` : ""}</dd></div><div><dt>Routing</dt><dd>{String(config.provider_mode ?? "—")} · {String(config.routing_strategy ?? "—")} · {modelNames}</dd></div></dl></details>;
}

export function EvaluationsPage() {
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<CaseIdentity | null>(null);
  const [failedOnly, setFailedOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runConfirmationOpen, setRunConfirmationOpen] = useState(false);
  const [historyLimit, setHistoryLimit] = useState(10);
  const [error, setError] = useState<string | null>(null);
  const selectionRequest = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const summaries = await client.getEvaluationRuns();
      const ordered = [...summaries].sort((left, right) => new Date(right.started_at).getTime() - new Date(left.started_at).getTime());
      setRuns(ordered);
      const nextId = ordered[0]?.id;
      if (nextId) {
        const detail = await client.getEvaluationRun(nextId);
        setRuns((current) => current.map((run) => run.id === detail.id ? detail : run));
        setSelectedId(detail.id);
        const first = detail.results?.find((result) => result.configuration === "improved") ?? detail.results?.[0];
        setSelectedCase(first ? resultIdentity(first) : null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load evaluation runs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const selected = runs.find((run) => run.id === selectedId) ?? null;
  const baselineMetrics = selected?.configuration_metrics?.baseline;
  const improvedMetrics = selected?.configuration_metrics?.improved ?? selected?.metrics;
  const allResults = selected?.results ?? [];
  const availableConfigurations = useMemo(() => Array.from(new Set(allResults.map((result) => result.configuration ?? "improved"))), [allResults]);
  const activeConfiguration = selectedCase?.configuration ?? (availableConfigurations.includes("improved") ? "improved" : availableConfigurations[0] ?? "improved");
  const results = allResults.filter((result) => (result.configuration ?? "improved") === activeConfiguration);
  const visibleResults = failedOnly ? results.filter((result) => !result.passed) : results;
  const selectedResult = visibleResults.find((result) => sameIdentity(result, selectedCase)) ?? visibleResults[0] ?? null;
  const categoryCount = useMemo(() => new Set(results.map((result) => result.category).filter(Boolean)).size, [results]);
  const dataset = datasetSnapshot(selected);
  const baselineProfile = configurationProfile(selected, "baseline", "Semantic vector retrieval only, and retrieval runs only when the classifier explicitly asks for knowledge. Routing and safety policy stay the same.");
  const improvedProfile = configurationProfile(selected, "improved", "Hybrid semantic + keyword retrieval with domain query expansion, plus opportunistic evidence retrieval for tool requests. The dataset and scoring gates stay the same.");
  const repeatabilityNote = String(record(selected?.config).repeatability_note ?? "Unchanged deterministic code may repeat quality scores while machine latency moves; code, corpus, model, or configuration changes should produce a measurable regression or gain.");
  const runInProgress = running || selected?.status === "running";
  const selectedInvalid = selected?.status === "invalid" || selected?.provenance_valid === false;
  const selectedFailed = selected?.status === "failed";
  const selectedLegacy = Boolean(selected && !selectedInvalid && !selectedFailed && selected.status !== "running" && !hasComparableProvenance(selected));
  const selectedComparable = Boolean(selected && !selectedInvalid && !selectedFailed && !selectedLegacy && selected.status !== "running");

  useEffect(() => {
    if (!selectedId || selected?.status !== "running") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await client.getEvaluationRun(selectedId);
        if (cancelled) return;
        setRuns((current) => current.map((run) => run.id === detail.id ? detail : run));
        if (detail.status !== "running" && detail.results?.length) {
          setError(null);
          const preserved = detail.results.find((result) => sameIdentity(result, selectedCase));
          const first = detail.results.find((result) => result.configuration === "improved") ?? detail.results[0];
          setSelectedCase(resultIdentity(preserved ?? first!));
        }
      } catch {
        // A transient polling failure must not start another paid run. The
        // next interval or a manual page refresh can recover the persisted job.
      }
    };
    const timer = window.setInterval(() => void poll(), 4_000);
    void poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selected?.status, selectedCase, selectedId]);

  async function runEvaluation() {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      const created = await client.runEvaluation({ name: "Baseline vs improved", configurations: ["baseline", "improved"] });
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      setSelectedId(created.id);
      const first = created.results?.find((result) => result.configuration === "improved") ?? created.results?.[0];
      setSelectedCase(first ? resultIdentity(first) : null);
    } catch (reason) {
      try {
        const summaries = await client.getEvaluationRuns();
        const persisted = [...summaries].sort((left, right) => new Date(right.started_at).getTime() - new Date(left.started_at).getTime()).find((run) => run.status === "running");
        if (persisted) {
          setRuns((current) => [persisted, ...current.filter((run) => run.id !== persisted.id)]);
          setSelectedId(persisted.id);
          setError("The start connection ended before completion, but the persisted evaluation is still running. Nexora is polling that run and will not start a duplicate.");
          return;
        }
      } catch {
        // Preserve the original start error when run discovery also fails.
      }
      setError(reason instanceof Error ? reason.message : "The evaluation run could not be started.");
    } finally {
      setRunning(false);
    }
  }

  async function selectRun(run: EvaluationRun) {
    const requestId = ++selectionRequest.current;
    const preserved = selectedCase;
    setSelectedId(run.id);
    setLoadingRunId(run.id);
    setError(null);
    try {
      const detail = run.results?.length ? run : await client.getEvaluationRun(run.id);
      if (selectionRequest.current !== requestId) return;
      setRuns((current) => current.map((item) => item.id === detail.id ? detail : item));
      const exact = detail.results?.find((result) => sameIdentity(result, preserved));
      const sameCase = detail.results?.find((result) => result.case_id === preserved?.caseId);
      const fallback = detail.results?.find((result) => result.configuration === "improved") ?? detail.results?.[0];
      const next = exact ?? sameCase ?? fallback;
      setSelectedCase(next ? resultIdentity(next) : null);
    } catch (reason) {
      if (selectionRequest.current === requestId) setError(reason instanceof Error ? reason.message : "Unable to load this evaluation snapshot.");
    } finally {
      if (selectionRequest.current === requestId) setLoadingRunId(null);
    }
  }

  function selectConfiguration(configuration: string) {
    const exact = allResults.find((result) => result.case_id === selectedCase?.caseId && (result.configuration ?? "improved") === configuration);
    const first = allResults.find((result) => (result.configuration ?? "improved") === configuration);
    const next = exact ?? first;
    setSelectedCase(next ? resultIdentity(next) : { caseId: "", configuration });
  }

  return (
    <main className="page page--evaluations">
      <PageHeader title="Evaluations" meta="Controlled regression evidence" actions={<Button variant="primary" icon="play" onClick={() => setRunConfirmationOpen(true)} disabled={runInProgress}>{runInProgress ? "Evaluation running…" : "Run 80 executions"}</Button>} />
      {error ? <ErrorBanner message={error} retry={() => void load()} /> : null}
      <div className="evaluation-layout">
        <div className="evaluation-main">
          <section className="eval-protocol" aria-labelledby="eval-protocol-title">
            <div className="eval-protocol__lead"><span>Protocol / 01</span><h2 id="eval-protocol-title">Same questions. One controlled pipeline change.</h2><p>This screen compares persisted execution results; it does not replay placeholder data when you select history.</p></div>
            <dl>
              <div><dt>{dataset.name} · {dataset.version}</dt><dd>{dataset.caseCount} persisted regression cases in this snapshot covering factual, ambiguous, missing, conflicting, tool-use, high-risk, and prompt-injection requests. Expected intent, sources, tools, and escalation are declared per case.{dataset.sha256 ? ` Dataset hash ${dataset.sha256.slice(0, 12)}… makes the exact input set identifiable.` : " This legacy snapshot predates persisted dataset hashes."}</dd></div>
              <div><dt>{baselineProfile.label}</dt><dd>{baselineProfile.detail}</dd></div>
              <div><dt>{improvedProfile.label}</dt><dd>{improvedProfile.detail}</dd></div>
              <div><dt>Why keep run history?</dt><dd>Each run is an immutable snapshot. {repeatabilityNote}</dd></div>
            </dl>
          </section>
          <section className="evaluation-config" aria-label="Selected evaluation snapshot">
            <div><span>Dataset</span><strong>{dataset.name} · {dataset.version}</strong><small>{dataset.caseCount} cases · {categoryCount || "—"} categories{dataset.source ? ` · ${dataset.source}` : ""}</small></div>
            <div><span>Selected snapshot</span><strong>{selected?.name ?? "No run selected"}</strong><small><code>{selected ? selected.id.slice(0, 8) : "—"}</code> · persisted results</small></div>
            <div><span>Recorded</span><strong>{selected ? new Date(selected.started_at).toLocaleString() : "—"}</strong><small>{selectedInvalid ? "Invalid · not comparable" : selectedFailed ? "Failed · not comparable" : selectedLegacy ? "Legacy · not comparable" : selected?.status === "completed" || selected?.completed_at ? "Completed" : selected?.status ?? "Not run"}</small></div>
            <div><span>Configuration view</span><strong>{activeConfiguration}</strong><small>Case detail follows this configuration</small></div>
          </section>
          {selected ? <EvaluationProvenance run={selected} /> : null}
          {selectedInvalid ? <section className="eval-invalid-banner" role="alert"><span>Provenance check failed</span><h2>This snapshot is not valid comparison evidence.</h2><p>{selected?.invalid_reason ?? "The knowledge corpus or runtime fingerprint changed while this evaluation was running."} Aggregate metrics and the trade-off plot are withheld; persisted case rows remain visible only for diagnosis.</p></section> : null}
          {selectedFailed ? <section className="eval-invalid-banner eval-invalid-banner--failed" role="alert"><span>Execution failed</span><h2>This run did not complete and is not comparison evidence.</h2><p>The evaluator or request pipeline stopped before a trustworthy aggregate snapshot was produced. Aggregate metrics and the trade-off plot are withheld; any persisted case rows below are diagnostic only.</p></section> : null}
          {selectedLegacy ? <section className="eval-invalid-banner" role="alert"><span>Comparable provenance missing</span><h2>This legacy snapshot is not comparison evidence.</h2><p>The run lacks one or more persisted dataset, evaluator, pipeline, corpus or route identity hashes required for a reproducible comparison. Aggregate metrics and the trade-off plot are withheld; case rows remain diagnostic only.</p></section> : null}
          {loading ? <LoadingRows rows={8} /> : selectedComparable ? (
            <section className="metric-comparison">
              <div className="table-scroll">
                <table className="data-table eval-metric-table">
                  <caption>Baseline and improved results recorded in the selected run. Delta is improved minus baseline.</caption>
                  <thead><tr><th>Metric</th><th>Baseline <InfoTip label="Baseline column" children="The reference pipeline measured in this same run." /></th><th>Improved <InfoTip label="Improved column" children="The hybrid-retrieval pipeline measured against the same cases." /></th><th>Delta <InfoTip label="Delta column" children="Improved minus baseline. Green means the change moved in the desired direction; for latency, cost, and failure rate, lower is better." /></th></tr></thead>
                  <tbody>{METRICS.map((metric) => {
                    const current = metricValue(improvedMetrics, metric.key);
                    const previous = metricValue(baselineMetrics, metric.key);
                    const delta = deltaLabel(current, previous, metric);
                    return <tr key={metric.key}><td><span className="eval-metric-name">{metric.label}<InfoTip label={metric.label} children={metric.definition} /></span></td><td>{previous === undefined ? "—" : metric.format(previous)}</td><td><strong>{current === undefined ? "—" : metric.format(current)}</strong></td><td className={`delta-${delta.tone}`}>{delta.text}</td></tr>;
                  })}</tbody>
                </table>
              </div>
              <TradeoffPlot baseline={baselineMetrics} improved={improvedMetrics} />
            </section>
          ) : selected ? null : <EmptyState title="No evaluation runs" message="Run the 40-case suite across both configurations to generate measured comparison results." action={<Button variant="primary" icon="play" onClick={() => setRunConfirmationOpen(true)}>Run 80 executions</Button>} />}
          {selected ? <section className="case-results">
            <div className="case-toolbar"><h2>{selectedComparable ? "Case results" : "Diagnostic case results"}</h2><div className="eval-config-switch" role="group" aria-label="Case configuration">{availableConfigurations.map((configuration) => <button key={configuration} type="button" aria-pressed={activeConfiguration === configuration} onClick={() => selectConfiguration(configuration)}>{configuration}</button>)}</div><label className="toggle"><input type="checkbox" checked={failedOnly} onChange={(event) => setFailedOnly(event.target.checked)} /><span>Failed only</span></label><span>{visibleResults.length} of {results.length} cases</span></div>
            {loadingRunId === selected.id ? <LoadingRows rows={6} /> : visibleResults.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Case ID</th><th>Category</th><th>Model</th><th>Score</th><th>Result</th><th>Latency</th><th>Cost</th></tr></thead><tbody>{visibleResults.map((result) => <tr key={result.id} className={result.id === selectedResult?.id ? "selected-row" : ""} onClick={() => setSelectedCase(resultIdentity(result))} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter") setSelectedCase(resultIdentity(result)); }}><td><button className="row-link" onClick={(event) => { event.stopPropagation(); setSelectedCase(resultIdentity(result)); }}>{result.case_id}</button></td><td>{result.category ?? "—"}</td><td><code>{result.model ?? "—"}</code></td><td>{result.correctness_score === undefined ? "—" : result.correctness_score.toFixed(2)}</td><td><StatusMark tone={result.passed ? "success" : "danger"}>{result.passed ? "Passed" : "Failed"}</StatusMark></td><td>{formatDuration(result.latency_ms)}</td><td>{result.estimated_cost === undefined ? "—" : formatMoney(result.estimated_cost)}</td></tr>)}</tbody></table></div> : <EmptyState title="No matching cases" message={failedOnly ? `Every ${activeConfiguration} case passed in this run.` : "This run has no persisted results for the selected configuration."} />}
          </section> : null}
          {runs.length ? <section className="run-history"><div className="run-history__heading"><div><span>Immutable snapshots</span><h2>Run history</h2></div><p>Selecting a snapshot loads its own persisted metrics, dataset provenance and case results. The current case ID and configuration are preserved when a matching case exists.</p></div><ol>{runs.slice(0, historyLimit).map((run) => {
            const metrics = run.configuration_metrics?.improved ?? run.metrics;
            const notComparable = run.status === "invalid" || run.status === "failed" || run.provenance_valid === false || !hasComparableProvenance(run);
            return <li key={run.id} className={run.id === selected?.id ? "selected" : ""}><span className="trace-node" /><button aria-pressed={run.id === selected?.id} onClick={() => void selectRun(run)} disabled={loadingRunId === run.id}><time>{new Date(run.started_at).toLocaleString()}</time><strong>{run.name}</strong><code>{run.id.slice(0, 8)}</code><span>{notComparable ? <b>Not comparable</b> : <><b>{metrics?.pass_rate === undefined ? "—" : formatPercent(metrics.pass_rate)}</b> pass · <b>{metrics?.p95_latency_ms === undefined ? "—" : formatDuration(metrics.p95_latency_ms)}</b> p95</>}</span><small>{loadingRunId === run.id ? "Loading snapshot…" : notComparable ? run.status ?? "invalid" : run.status ?? (run.completed_at ? "completed" : "running")}</small></button></li>;
          })}</ol>{runs.length > historyLimit ? <footer className="run-history__more"><Button onClick={() => setHistoryLimit((current) => Math.min(runs.length, current + 10))}>Show next {Math.min(10, runs.length - historyLimit)} runs</Button><span>{historyLimit} of {runs.length} loaded snapshots shown</span></footer> : null}</section> : null}
        </div>
        <aside className="evaluation-detail" aria-label="Evaluation case detail">
          {selectedResult ? <CaseDetail result={selectedResult} runId={selected?.id ?? ""} /> : <EmptyState title="Select a case" message={failedOnly ? "No failed cases match this configuration." : "Inspect a case and its grounded scoring evidence."} />}
        </aside>
      </div>
      {runConfirmationOpen ? <div className="eval-confirm-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setRunConfirmationOpen(false); }}><section className="eval-confirm" role="alertdialog" aria-modal="true" aria-labelledby="eval-confirm-title" aria-describedby="eval-confirm-description" onKeyDown={(event) => { if (event.key === "Escape") setRunConfirmationOpen(false); }}><span>Cost checkpoint</span><h2 id="eval-confirm-title">Run the full comparison?</h2><p id="eval-confirm-description">{NEW_RUN_DATASET.caseCount} cases × {NEW_RUN_CONFIGURATIONS} configurations = <strong>{NEW_RUN_DATASET.caseCount * NEW_RUN_CONFIGURATIONS} sequential pipeline executions</strong>. If a remote model provider is active, these calls can consume tokens and incur provider charges. Nexora records an estimate; the provider bill remains authoritative.</p><dl><div><dt>Dataset</dt><dd>{NEW_RUN_DATASET.name} · {NEW_RUN_DATASET.version}</dd></div><div><dt>Configurations</dt><dd>Baseline + improved</dd></div><div><dt>Executions</dt><dd>{NEW_RUN_DATASET.caseCount * NEW_RUN_CONFIGURATIONS}</dd></div></dl><footer><Button autoFocus onClick={() => setRunConfirmationOpen(false)}>Cancel</Button><Button variant="primary" icon="play" onClick={() => { setRunConfirmationOpen(false); void runEvaluation(); }}>Confirm &amp; run {NEW_RUN_DATASET.caseCount * NEW_RUN_CONFIGURATIONS}</Button></footer></section></div> : null}
    </main>
  );
}

function TradeoffPlot({ baseline, improved }: { baseline?: EvaluationMetricSet; improved?: EvaluationMetricSet }) {
  const series = [
    baseline ? { name: "Baseline", metrics: baseline, className: "plot-dot--baseline" } : null,
    improved ? { name: "Improved", metrics: improved, className: "plot-dot--improved" } : null,
  ].filter((item): item is { name: string; metrics: EvaluationMetricSet; className: string } => Boolean(
    item && item.metrics.pass_rate !== undefined && item.metrics.p95_latency_ms !== undefined,
  ));
  if (!series.length) {
    return <figure className="quality-plot" aria-label="Quality, speed, and cost trade-off unavailable"><div className="section-heading"><div><span>Trade-off map</span><h2>Pass rate vs. latency / cost</h2></div></div><EmptyState title="No comparable measurements" message="This snapshot does not contain both pass-rate and P95-latency metrics, so Nexora will not plot invented zero values." /></figure>;
  }
  const maxLatency = Math.max(1, ...series.map((item) => item.metrics.p95_latency_ms ?? 0)) * 1.2;
  const costsKnown = series.every((item) => item.metrics.estimated_cost !== undefined);
  const maxCost = Math.max(0, ...series.map((item) => item.metrics.estimated_cost ?? 0));
  const x = (latency: number) => 54 + Math.min(1, latency / maxLatency) * 360;
  const y = (passRate: number) => 198 - Math.min(1, passRate) * 158;
  const radius = (cost: number | undefined) => costsKnown && maxCost > 0 ? 7 + ((cost ?? 0) / maxCost) * 8 : 8;
  const aria = series.map((item) => `${item.name}: ${formatPercent(item.metrics.pass_rate ?? 0)} pass rate, ${formatDuration(item.metrics.p95_latency_ms ?? 0)} P95 latency, ${item.metrics.estimated_cost === undefined ? "cost unavailable" : `${formatMoney(item.metrics.estimated_cost)} cost`}`).join(". ");

  return (
    <figure className="quality-plot" aria-label={`Quality, speed, and cost trade-off. ${aria}`}>
      <div className="section-heading"><div><span>Trade-off map</span><h2>Pass rate vs. latency / cost</h2></div><span className="plot-ideal">Ideal ↖</span></div>
      <svg viewBox="0 0 470 250" role="img" aria-hidden="true">
        {[0, 0.5, 1].map((value) => {
          const position = y(value);
          return <g key={`y-${value}`}><line x1="54" x2="432" y1={position} y2={position} className="chart-grid" /><text x="44" y={position + 3} textAnchor="end">{formatPercent(value)}</text></g>;
        })}
        {[0, 0.5, 1].map((value) => {
          const position = 54 + value * 360;
          return <g key={`x-${value}`}><line x1={position} x2={position} y1="30" y2="198" className="chart-grid" /><text x={position} y="218" textAnchor="middle">{formatDuration(maxLatency * value)}</text></g>;
        })}
        <line x1="54" x2="432" y1="198" y2="198" className="plot-axis" /><line x1="54" x2="54" y1="30" y2="198" className="plot-axis" />
        {series.map((item, index) => {
          const cx = x(item.metrics.p95_latency_ms ?? 0);
          const cy = y(item.metrics.pass_rate ?? 0);
          return <g key={item.name}><circle cx={cx} cy={cy} r={radius(item.metrics.estimated_cost)} className={`plot-dot ${item.className}`}><title>{`${item.name}: ${formatPercent(item.metrics.pass_rate ?? 0)}, ${formatDuration(item.metrics.p95_latency_ms ?? 0)}, ${item.metrics.estimated_cost === undefined ? "cost unavailable" : formatMoney(item.metrics.estimated_cost)}`}</title></circle><text x={Math.min(405, cx + 12)} y={cy + (index ? -9 : 17)} className="plot-point-label">{item.name}</text></g>;
        })}
        <text x="243" y="241" textAnchor="middle">P95 latency · slower →</text>
        <text x="13" y="114" transform="rotate(-90 13 114)" textAnchor="middle">Pass rate · better →</text>
      </svg>
      <div className="plot-legend"><span><i className="plot-dot-label plot-dot-label--baseline" />Baseline</span><span><i className="plot-dot-label plot-dot-label--improved" />Improved</span></div>
      <figcaption>Up means more cases passed; right means slower P95 execution; circle size represents total recorded cost. {!costsKnown ? "This legacy snapshot did not persist cost, so neutral circle sizes are used instead of inventing $0." : maxCost === 0 ? "Both circles use the minimum size because this snapshot records $0; provider provenance determines whether that means mock execution or missing configured prices." : "The best trade-off sits toward the upper-left with the smaller circle."}</figcaption>
    </figure>
  );
}

function CaseDetail({ result, runId }: { result: EvaluationResult; runId: string }) {
  const details = result.details ?? {};
  return (
    <>
      <header><div><code>{result.case_id}</code><small className="evaluation-detail__run">run {runId.slice(0, 8)} · {result.configuration ?? "improved"}</small></div><StatusMark tone={result.passed ? "success" : "danger"}>{result.passed ? "Passed" : "Failed"}</StatusMark></header>
      <dl className="review-metadata"><div><dt>Category</dt><dd>{result.category ?? "—"}</dd></div><div><dt>Groundedness</dt><dd>{result.groundedness_score === undefined ? "—" : result.groundedness_score.toFixed(2)}</dd></div><div><dt>Retrieval</dt><dd>{result.retrieval_score === undefined ? "—" : result.retrieval_score.toFixed(2)}</dd></div></dl>
      {Object.entries(details).map(([key, value]) => <section key={key}><h2>{key.replaceAll("_", " ")}</h2><div className={`read-only-field${key.includes("error") || key.includes("failure") ? " read-only-field--danger" : ""}`}>{typeof value === "string" ? value : <pre>{JSON.stringify(value, null, 2)}</pre>}</div></section>)}
      <section><h2>Measured execution</h2><dl className="definition-list definition-list--stacked"><div><dt>Configuration</dt><dd>{result.configuration ?? "—"}</dd></div><div><dt>Model</dt><dd>{result.model ?? "—"}</dd></div><div><dt>Latency</dt><dd>{formatDuration(result.latency_ms)}</dd></div><div><dt>Estimated cost</dt><dd>{result.estimated_cost === undefined ? "—" : formatMoney(result.estimated_cost)}</dd></div></dl></section>
    </>
  );
}
