import { useEffect, useMemo, useState, type FormEvent } from "react";
import { client } from "../api/client";
import { MarkdownContent } from "../components/MarkdownContent";
import { SourceDocumentDialog } from "../components/SourceDocumentDialog";
import { Button, ErrorBanner, PageHeader, StatusMark, formatDuration, formatMoney, formatPercent } from "../components/Ui";
import type { AvailableModel, Channel, Citation, RequestResult, RoutingStrategy } from "../types";

const CHANNELS: Channel[] = ["web", "email", "slack", "api"];
const PIPELINE_STAGES = ["classify", "retrieve", "route", "generate", "validate"] as const;
type PipelineStage = (typeof PIPELINE_STAGES)[number];
type PipelineStageState = "Complete" | "Needs review" | "Failed" | "Skipped" | "Pending" | "Running";

const ROUTING_OPTIONS: Array<{ value: RoutingStrategy; label: string; description: string }> = [
  { value: "cheapest_adequate", label: "Automatic · balanced", description: "Selects the least expensive model that meets the request’s risk and complexity requirements." },
  { value: "quality_first", label: "Automatic · quality first", description: "Prefers the strongest eligible model, then falls back if the provider fails." },
  { value: "latency_first", label: "Automatic · latency first", description: "Prefers the fastest eligible model while preserving risk policy." },
  { value: "fallback_chain", label: "Resilient fallback chain", description: "Runs the configured model chain in order until an eligible provider succeeds." },
  { value: "explicit_model", label: "Manual model", description: "Uses the selected model unless safety or availability requires a fallback." },
];

const STAGE_TIMING_KEYS: Record<PipelineStage, string[]> = {
  classify: ["classify", "classification_ms"],
  retrieve: ["retrieve", "retrieval_ms"],
  route: ["route", "routing_ms"],
  generate: ["generate", "generation_ms", "model_ms"],
  validate: ["validate", "validation_and_persistence_ms"],
};

function humanize(value?: string | null) {
  if (!value) return "—";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function StageDetail({ stage, result, strategy }: { stage: PipelineStage; result: RequestResult | null; strategy: RoutingStrategy }) {
  if (!result) return <p className="pipeline-detail-empty">Run a request to see measured inputs, decisions and outputs for this step.</p>;
  const citations = result.citations ?? [];
  const attempts = result.provider_attempts ?? [];
  const calls = result.tool_calls ?? [];
  const topScore = citations.reduce((best, citation) => Math.max(best, citation.score ?? 0), 0);
  if (stage === "classify") return <dl className="stage-evidence"><div><dt>Topic</dt><dd>{humanize(result.topic ?? result.intent)}</dd></div><div><dt>Topic basis</dt><dd>{result.topic_reason ?? result.classification_reason ?? "The classifier did not return a topic rationale."}</dd></div><div><dt>Intent type</dt><dd>{humanize(result.intent)}</dd></div><div><dt>Risk</dt><dd>{humanize(result.risk_level)} · {result.risk_reason ?? "policy assessment"}</dd></div><div><dt>Risk evidence</dt><dd>{result.risk_factors?.length ? result.risk_factors.join(" · ") : "No explicit risk factors were returned."}</dd></div><div><dt>Required work</dt><dd>{[result.needs_retrieval ? "knowledge retrieval" : null, result.needs_tools ? "approved tools" : null].filter(Boolean).join(" + ") || "direct response"}</dd></div></dl>;
  if (stage === "retrieve") {
    const recordedAttempt = result.decision_factors?.retrieval_attempted;
    const retrievalStatus = String(result.decision_factors?.retrieval_status ?? "");
    const retrievalRan = typeof recordedAttempt === "boolean" ? recordedAttempt : citations.length > 0 || STAGE_TIMING_KEYS.retrieve.some((key) => (result.stage_timings?.[key] ?? 0) > 0);
    const retrievalMode = String(result.decision_factors?.retrieval_mode ?? "");
    const decision = retrievalStatus === "failed"
      ? "Retrieval was attempted but failed before a trustworthy evidence result was produced"
      : result.needs_retrieval
      ? "Retrieval required by classification"
      : retrievalRan && retrievalMode === "opportunistic_tool_evidence"
        ? "Opportunistic retrieval ran to ground a tool or policy-sensitive request, although classification did not require knowledge"
        : "Retrieval was not required and was skipped";
    return <dl className="stage-evidence"><div><dt>Decision</dt><dd>{decision}</dd></div><div><dt>Evidence</dt><dd>{citations.length} cited chunks across {new Set(citations.map((item) => item.document_id ?? item.title)).size} documents</dd></div><div><dt>Top relevance</dt><dd>{citations.length ? `${formatPercent(topScore)} similarity` : "No adequate match"}</dd></div><div><dt>Ranking</dt><dd>Improved mode blends 60% semantic similarity with 40% keyword coverage; policy gates can still require human review.</dd></div></dl>;
  }
  if (stage === "route") return <><dl className="stage-evidence"><div><dt>Strategy</dt><dd>{humanize(String(result.decision_factors?.strategy ?? strategy))}</dd></div><div><dt>Selected model</dt><dd><code>{result.model_used ?? "No model completed"}</code></dd></div><div><dt>Why</dt><dd>{result.route_reason ?? "No route rationale was returned."}</dd></div></dl>{attempts.length ? <ol className="provider-attempts">{attempts.map((attempt, index) => <li key={attempt.id ?? `${attempt.model}-${index}`}><StatusMark tone={attempt.success ? "success" : "danger"}>{attempt.success ? "success" : "failed"}</StatusMark><code>{humanize(attempt.purpose)} · {attempt.provider} · {attempt.model}</code><span>{formatDuration(attempt.latency_ms ?? 0)} · {formatMoney(attempt.estimated_cost ?? 0)} · {(attempt.prompt_tokens ?? 0) + (attempt.completion_tokens ?? 0)} tokens · {attempt.retries ?? 0} retries</span>{attempt.error ? <small>{attempt.error}</small> : null}</li>)}</ol> : <p className="pipeline-detail-note">No provider-attempt audit records were returned for this trace.</p>}</>;
  if (stage === "generate") return <dl className="stage-evidence"><div><dt>Model</dt><dd><code>{result.model_used ?? "—"}</code></dd></div><div><dt>Token usage</dt><dd>{result.tokens_in ?? 0} input + {result.tokens_out ?? 0} output</dd></div><div><dt>Tool execution</dt><dd>{calls.length ? `${calls.length} allowlisted call${calls.length === 1 ? "" : "s"}` : "No tools were required"}</dd></div><div><dt>Output</dt><dd>{result.response?.length ?? 0} characters, grounded against {citations.length} citations</dd></div></dl>;
  return <dl className="stage-evidence"><div><dt>Final status</dt><dd>{result.status === "failed" ? "Failed · Needs review" : result.requires_review ? "Needs review" : humanize(result.status)}</dd></div><div><dt>Confidence</dt><dd>{formatPercent(result.confidence)} workflow heuristic</dd></div><div><dt>Citation check</dt><dd>{citations.length ? `${citations.length} structured citations persisted` : "No citations required or available"}</dd></div><div><dt>Escalation gates</dt><dd>{result.escalation_reasons?.length ? result.escalation_reasons.join("; ") : "All configured safety gates passed"}</dd></div></dl>;
}

function resolvedStageState(stage: PipelineStage, result: RequestResult | null): PipelineStageState {
  if (!result) return "Pending";
  const recordedRetrievalAttempt = result.decision_factors?.retrieval_attempted;
  const retrievalStatus = String(result.decision_factors?.retrieval_status ?? "");
  const retrievalRan = typeof recordedRetrievalAttempt === "boolean" ? recordedRetrievalAttempt : Boolean(result.citations?.length || STAGE_TIMING_KEYS.retrieve.some((key) => (result.stage_timings?.[key] ?? 0) > 0));
  if (result.status !== "failed") {
    if (stage === "retrieve" && (retrievalStatus === "skipped" || result.needs_retrieval === false && !retrievalRan)) return "Skipped";
    if (stage === "validate" && result.requires_review) return "Needs review";
    return "Complete";
  }
  const positiveTiming = STAGE_TIMING_KEYS[stage].some((key) => (result.stage_timings?.[key] ?? 0) > 0);
  const classified = Boolean(result.intent || result.topic || result.classification_reason || STAGE_TIMING_KEYS.classify.some((key) => result.stage_timings?.[key] !== undefined));
  const routed = Boolean(result.route_reason || result.model_used || result.provider_attempts?.length || STAGE_TIMING_KEYS.route.some((key) => result.stage_timings?.[key] !== undefined));
  const generated = Boolean(result.provider_attempts?.some((attempt) => attempt.success) || result.tokens_out || result.tool_calls?.length || (result.response && result.model_used));
  if (stage === "classify") return classified ? "Complete" : "Failed";
  if (stage === "retrieve") {
    if (!classified) return "Skipped";
    if (retrievalStatus === "failed") return "Failed";
    if (retrievalStatus === "skipped" || result.needs_retrieval === false && !retrievalRan) return "Skipped";
    if (retrievalStatus === "completed") return "Complete";
    return positiveTiming || Boolean(result.citations?.length) ? "Complete" : "Failed";
  }
  if (stage === "route") return routed ? "Complete" : classified ? "Failed" : "Skipped";
  if (stage === "generate") {
    if (generated) return "Complete";
    return routed ? "Failed" : "Skipped";
  }
  return "Failed";
}

function PipelineInspector({ result, running, strategy }: { result: RequestResult | null; running: boolean; strategy: RoutingStrategy }) {
  const [progressStage, setProgressStage] = useState(0);
  const [selectedStage, setSelectedStage] = useState<PipelineStage>("classify");
  useEffect(() => {
    if (!running) { setProgressStage(0); return; }
    const timer = window.setInterval(() => setProgressStage((current) => Math.min(current + 1, PIPELINE_STAGES.length - 1)), 700);
    return () => window.clearInterval(timer);
  }, [running]);
  const confidenceDetails = Object.entries(result?.confidence_details ?? {});
  const method = confidenceDetails.find(([, raw]) => typeof raw === "string")?.[1];
  const fallbackRiskFactors = Object.entries(result?.decision_factors ?? {}).filter(([key]) => key.toLowerCase().includes("risk")).map(([key, value]) => `${humanize(key)}: ${String(value)}`);
  const riskFactors = result?.risk_factors?.length ? result.risk_factors : fallbackRiskFactors;
  return <aside className="pipeline-inspector" aria-label="Pipeline inspector">
    <div className="pipeline-stages" aria-label="Pipeline steps">{PIPELINE_STAGES.map((stage, index) => {
      const active = running && index === progressStage;
      const state = running ? active ? "Running" : index < progressStage ? "Complete" : "Pending" : resolvedStageState(stage, result);
      const review = state === "Needs review";
      const failed = state === "Failed";
      const skipped = state === "Skipped";
      const timing = STAGE_TIMING_KEYS[stage].map((key) => result?.stage_timings?.[key]).find((value) => value !== undefined);
      return <button type="button" className={`pipeline-stage${active ? " pipeline-stage--active" : ""}${review ? " pipeline-stage--review" : ""}${failed ? " pipeline-stage--failed" : ""}${skipped ? " pipeline-stage--skipped" : ""}${selectedStage === stage ? " pipeline-stage--selected" : ""}`} key={stage} aria-expanded={selectedStage === stage} aria-controls="pipeline-stage-detail" onClick={() => setSelectedStage(stage)}><span className="pipeline-stage__node" /><strong>{humanize(stage)}</strong><span>{state}</span><code>{timing !== undefined ? formatDuration(timing) : "—"}</code></button>;
    })}</div>
    {running ? <p className="pipeline-progress-note" aria-live="polite">Estimated progress; measured timings arrive with the completed trace.</p> : null}
    <section className="pipeline-stage-detail" id="pipeline-stage-detail" aria-live="polite"><header><span>Step evidence</span><strong>{humanize(selectedStage)}</strong></header><StageDetail stage={selectedStage} result={result} strategy={strategy} /></section>
    <section className="inspector-section inspector-grid inspector-grid--three"><div><span>Topic</span><strong>{humanize(result?.topic ?? result?.intent)}</strong></div><div><span>Intent type</span><strong>{humanize(result?.intent)}</strong></div><div><span>Risk</span><strong>{humanize(result?.risk_level)}</strong></div></section>
    <section className="inspector-section inspector-explanation"><h2>How the decision was made</h2><dl className="definition-list"><div><dt>Topic</dt><dd>{result?.topic_reason ?? result?.classification_reason ?? "Awaiting classifier evidence."}</dd></div><div><dt>Risk basis</dt><dd>{result?.risk_reason ? `${result.risk_reason}${riskFactors.length ? ` Evidence: ${riskFactors.join(" · ")}` : ""}` : riskFactors.length ? riskFactors.join(" · ") : "Safety rules consider financial impact, identity or access changes, reversibility and adversarial language."}</dd></div><div><dt>Model choice</dt><dd>{result?.route_reason ?? ROUTING_OPTIONS.find((item) => item.value === strategy)?.description}</dd></div></dl></section>
    <section className="inspector-section"><h2>Confidence <span>(workflow heuristic, not probability)</span></h2><strong className="confidence-total">{result ? formatPercent(result.confidence) : "—"}</strong><div className="confidence-list">{confidenceDetails.map(([label, raw]) => { if (typeof raw !== "number" && typeof raw !== "boolean") return null; const value = typeof raw === "boolean" ? (raw ? 1 : 0) : raw; return <div key={label}><span>{humanize(label)}</span><code>{typeof raw === "boolean" ? String(raw) : value.toFixed(2)}</code><span className="confidence-bar"><i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></span></div>; })}</div>{typeof method === "string" ? <p className="confidence-note">{method}</p> : <p className="confidence-note">The score combines retrieval quality, output structure, grounding and tool outcome; thresholds are workflow policy, not calibrated likelihood.</p>}</section>
    <footer className="inspector-footer"><div><span>Estimated cost</span><strong>{formatMoney(result?.estimated_cost ?? 0)}</strong></div><div><span>Total tokens</span><strong>{(result?.tokens_in ?? 0) + (result?.tokens_out ?? 0)}</strong></div><div><span>Latency</span><strong>{formatDuration(result?.latency_ms ?? 0)}</strong></div></footer>
  </aside>;
}

export function RequestConsolePage() {
  const [channel, setChannel] = useState<Channel>("web");
  const [userId, setUserId] = useState("CUST-1002");
  const [message, setMessage] = useState("Customer CUST-1002 says their card is stolen. What should we do?");
  const [routingStrategy, setRoutingStrategy] = useState<RoutingStrategy>("cheapest_adequate");
  const [explicitModel, setExplicitModel] = useState("");
  const [models, setModels] = useState<AvailableModel[]>([]);
  const [modelDiscoveryFailed, setModelDiscoveryFailed] = useState(false);
  const [result, setResult] = useState<RequestResult | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasUnverifiedRemoteModels = models.some((model) => model.availability === "configured_unverified");
  useEffect(() => { let cancelled = false; void client.getModels().then((available) => { if (cancelled) return; const eligible = available.filter((model) => model.enabled !== false && !model.fallback_only); setModels(eligible); setExplicitModel((current) => eligible.some((model) => model.model === current) ? current : eligible[0]?.model ?? ""); setModelDiscoveryFailed(false); }).catch(() => { if (!cancelled) { setModels([]); setExplicitModel(""); setModelDiscoveryFailed(true); } }); return () => { cancelled = true; }; }, []);
  const routeDescription = useMemo(() => ROUTING_OPTIONS.find((item) => item.value === routingStrategy)?.description ?? "", [routingStrategy]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!message.trim() || running) return;
    setRunning(true); setError(null); setResult(null); setSelectedCitation(null);
    try { setResult(await client.createRequest({ channel, user_id: userId.trim() || null, message: message.trim(), metadata: { console: true }, routing_strategy: routingStrategy, explicit_model: routingStrategy === "explicit_model" ? explicitModel : undefined })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The request could not be processed."); }
    finally { setRunning(false); }
  }
  const responseFailed = result?.status === "failed";
  const responseStatus = responseFailed ? "Failed · Needs review" : result?.requires_review ? "Needs review" : result?.status === "completed" ? "Completed" : humanize(result?.status);
  return <main className="page page--console">
    <PageHeader title="Request Console" meta={result ? <><code>Trace ID: {result.trace_id ?? result.request_id}</code><StatusMark tone={responseFailed ? "danger" : result.requires_review ? "warning" : "success"}>{responseStatus}</StatusMark></> : undefined} />
    <div className="console-layout"><div className="console-main">
      <form className="request-form" onSubmit={(event) => void submit(event)}>
        <div className="request-form__top"><fieldset><legend>Channel</legend><div className="segmented-control">{CHANNELS.map((item) => <button key={item} type="button" aria-pressed={channel === item} className={channel === item ? "selected" : ""} onClick={() => setChannel(item)}>{item}</button>)}</div></fieldset><label className="field"><span>User ID</span><input value={userId} onChange={(event) => setUserId(event.target.value)} maxLength={100} /></label></div>
        <div className="routing-controls"><label className="field"><span>Routing strategy</span><select value={routingStrategy} onChange={(event) => setRoutingStrategy(event.target.value as RoutingStrategy)}>{ROUTING_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label className="field"><span>{routingStrategy === "explicit_model" ? "Selected model" : "Configured portfolio"}</span><select value={explicitModel} onChange={(event) => setExplicitModel(event.target.value)} disabled={routingStrategy !== "explicit_model" || !models.length}>{models.length ? models.map((model) => <option key={`${model.provider}:${model.model}`} value={model.model}>{model.display_name ?? model.model} · {model.role ?? model.provider}</option>) : <option value="">No remote models configured</option>}</select></label><p>{routeDescription}{modelDiscoveryFailed ? " Provider capability registry could not be loaded; manual model selection is disabled." : !models.length ? " No remote models are configured in this runtime; automatic routes may use the deterministic fallback." : hasUnverifiedRemoteModels ? " These routes are configured locally; live provider catalog availability has not been verified yet." : ""}</p></div>
        <label className="field field--textarea"><span>Message</span><textarea value={message} onChange={(event) => setMessage(event.target.value)} maxLength={12_000} rows={6} required /><small>{message.length} / 12000</small></label>
        <div className="form-actions"><button type="button" className="text-action" onClick={() => setMessage("")}>Clear</button><Button variant="primary" icon="play" type="submit" disabled={running || !message.trim() || (routingStrategy === "explicit_model" && !explicitModel)}>{running ? "Running pipeline…" : "Run request"}</Button></div>
      </form>
      {error ? <ErrorBanner message={error} /> : null}
      <section className={`response-section${result ? " response-section--visible" : ""}`} aria-live="polite"><div className="section-heading"><h2>Response</h2>{result?.latency_ms !== undefined ? <code>{formatDuration(result.latency_ms)}</code> : null}</div>
        {result ? <><div className={`response-outcome${responseFailed ? " response-outcome--failed" : result.requires_review ? " response-outcome--review" : " response-outcome--completed"}`}><StatusMark tone={responseFailed ? "danger" : result.requires_review ? "warning" : "success"}>{responseStatus}</StatusMark><div><strong>{responseFailed ? "Processing failed; investigation required" : result.requires_review ? "Human decision required before release" : "Automatic processing completed"}</strong><p>{result.requires_review ? (result.escalation_reasons?.join(" · ") || "A configured safety gate routed this response to the review queue.") : "Classification, evidence retrieval, generation and validation completed successfully."}</p></div></div>
          <div className="grounded-answer"><h3>Grounded answer</h3><MarkdownContent className="answer-content" text={result.response ?? "No automatic answer was returned. The request requires human review."} /></div>
          <div className="sources-section"><h3>Sources ({result.citations.length})</h3><p className="section-caption">Select a source to inspect the matched chunk, full document and relevance score.</p>{result.citations.length ? <ol className="source-list">{result.citations.map((citation, index) => <li key={`${citation.document_id ?? citation.title}:${citation.chunk_index ?? index}`}><span>{index + 1}</span><button type="button" className="source-link" onClick={() => setSelectedCitation(citation)}><strong>{citation.title}</strong><small>{citation.source}{citation.page_number ? ` · page ${citation.page_number}` : ""}</small></button><div className="source-score"><code>{citation.score === undefined ? "—" : formatPercent(citation.score)}</code><small>relevance</small></div></li>)}</ol> : <p className="inline-empty">No documents were cited for this request.</p>}</div>
          <div className="tool-calls"><h3>Tool execution ({result.tool_calls?.length ?? 0})</h3><p className="section-caption">Only allowlisted tools can run. Every argument, result, approval state and error is persisted here.</p>{result.tool_calls?.length ? result.tool_calls.map((call) => <details key={call.id ?? `${call.tool_name}:${call.latency_ms}`} open><summary><strong>{call.tool_name}</strong><StatusMark tone={["success", "completed", "succeeded"].includes(call.status) ? "success" : call.requires_approval ? "warning" : "danger"}>{call.status}</StatusMark><code>{formatDuration(call.latency_ms ?? 0)}</code></summary><div className="json-grid"><div><span>Arguments</span><pre>{JSON.stringify(call.arguments, null, 2)}</pre></div><div><span>Result</span><pre>{call.error ? `Error: ${call.error}\n\n` : ""}{JSON.stringify(call.result, null, 2)}</pre></div></div></details>) : <p className="inline-empty">No tool was executed. The router determined that retrieval and model generation were sufficient for this request.</p>}</div>
        </> : <div className="response-placeholder"><span className="trace-node" /><p>Run a request to inspect retrieval, routing, tools, validation and cost in one trace.</p></div>}
      </section>
    </div><PipelineInspector result={result} running={running} strategy={routingStrategy} /></div>
    <SourceDocumentDialog citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
  </main>;
}
