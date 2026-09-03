import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { formatMoney } from "../lib/format";
import { navigate } from "../lib/router";
import type { Dataset, ModelConfig, PromptVersion, RetrievalConfig, RunSummary } from "../types";
import { StatePanel } from "../components/StatePanel";
import { PageFrame, PageHeader } from "./OverviewPage";

interface BuilderData { datasets: Dataset[]; models: ModelConfig[]; prompts: PromptVersion[]; retrievals: RetrievalConfig[] }

export function ExperimentBuilderPage() {
  const [data, setData] = useState<BuilderData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("Quality and retrieval comparison");
  const [datasetId, setDatasetId] = useState("");
  const [modelIds, setModelIds] = useState<string[]>([]);
  const [promptIds, setPromptIds] = useState<string[]>([]);
  const [retrievalIds, setRetrievalIds] = useState<string[]>([]);
  const [judge, setJudge] = useState(true);
  const [injectFailures, setInjectFailures] = useState(false);
  const [maxCost, setMaxCost] = useState("2.00");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<Dataset[]>("/datasets"),
      api<ModelConfig[]>("/models"),
      api<PromptVersion[]>("/prompts"),
      api<RetrievalConfig[]>("/retrieval-configs"),
    ]).then(([datasets, models, prompts, retrievals]) => {
      if (!active) return;
      setData({ datasets, models, prompts, retrievals });
      setDatasetId(datasets[0]?.id ?? "");
      setModelIds(models.slice(0, 2).map((item) => item.id));
      setPromptIds(prompts.slice(0, 2).map((item) => item.id));
      setRetrievalIds(retrievals.slice(0, 1).map((item) => item.id));
    }).catch((reason: Error) => active && setError(reason.message));
    return () => { active = false; };
  }, []);

  const dataset = data?.datasets.find((item) => item.id === datasetId);
  const matrixSize = (dataset?.case_count ?? 0) * modelIds.length * promptIds.length * retrievalIds.length;
  const estimatedCost = useMemo(() => {
    if (!data) return null;
    const selected = data.models.filter((item) => modelIds.includes(item.id));
    if (!selected.length || selected.some((item) => item.input_price_per_million === null || item.output_price_per_million === null)) return null;
    const average = selected.reduce((sum, item) => sum + ((item.input_price_per_million ?? 0) * 180 + (item.output_price_per_million ?? 0) * 80) / 1_000_000, 0) / selected.length;
    return matrixSize * average;
  }, [data, matrixSize, modelIds]);

  const ready = Boolean(name.trim() && datasetId && modelIds.length && promptIds.length && retrievalIds.length && !starting);
  const toggle = (id: string, values: string[], setter: (next: string[]) => void) => setter(values.includes(id) ? values.filter((item) => item !== id) : [...values, id]);

  async function start() {
    if (!ready) return;
    setStarting(true);
    setError(null);
    try {
      const experiment = await api<{ id: string }>("/experiments", {
        method: "POST",
        body: JSON.stringify({
          name,
          dataset_id: datasetId,
          model_config_ids: modelIds,
          prompt_version_ids: promptIds,
          retrieval_config_ids: retrievalIds,
          evaluator_config: { enable_judge: judge, concurrency: 6, judge_model: judge ? "mock-judge-v1" : null },
          max_estimated_cost: maxCost ? Number(maxCost) : null,
        }),
      });
      const run = await api<RunSummary>(`/experiments/${experiment.id}/runs`, { method: "POST", body: JSON.stringify({ force_partial_failures: injectFailures }) });
      navigate(`/runs/${run.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run could not start");
      setStarting(false);
    }
  }

  if (!data && !error) return <PageFrame><StatePanel kind="loading" title="Loading experiment inputs">Reading registered datasets and configurations…</StatePanel></PageFrame>;
  if (!data) return <PageFrame><StatePanel kind="error" title="Builder unavailable">{error}</StatePanel></PageFrame>;
  if (!data.datasets.length || !data.models.length || !data.prompts.length || !data.retrievals.length) return <PageFrame><StatePanel kind="empty" title="Configurations are incomplete">Register at least one dataset, model, prompt and retrieval configuration.</StatePanel></PageFrame>;

  return (
    <PageFrame>
      <PageHeader title="Experiment builder" subtitle="Define an exact, reproducible generation matrix before execution" />
      {error ? <div className="inline-alert" role="alert"><strong>Run not started.</strong> {error}</div> : null}
      <div className="builder-layout">
        <div className="builder-form">
          <BuilderSection number="01" title="Identity and dataset">
            <label className="field"><span>Experiment name</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label className="field"><span>Dataset</span><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{data.datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version} · {item.case_count} cases</option>)}</select></label>
          </BuilderSection>
          <BuilderSection number="02" title="Model configurations">
            <ChoiceGrid items={data.models} selected={modelIds} onToggle={(id) => toggle(id, modelIds, setModelIds)} render={(item) => <><strong>{item.name}</strong><span>{item.provider} / {item.model}</span><small>temp {item.temperature} · max {item.max_tokens} · {item.retries} retries</small></>} />
          </BuilderSection>
          <BuilderSection number="03" title="Prompt versions">
            <ChoiceGrid items={data.prompts} selected={promptIds} onToggle={(id) => toggle(id, promptIds, setPromptIds)} render={(item) => <><strong>{item.name} v{item.semantic_version}</strong><span>{item.tags.join(" · ")}</span><small>{item.system_prompt}</small></>} />
          </BuilderSection>
          <BuilderSection number="04" title="Retrieval configurations">
            <ChoiceGrid items={data.retrievals} selected={retrievalIds} onToggle={(id) => toggle(id, retrievalIds, setRetrievalIds)} render={(item) => <><strong>{item.name}</strong><span>{item.mode} · top-{item.top_k}</span><small>chunk {item.chunk_size} · overlap {item.overlap} · reranker {item.reranker_enabled ? "on" : "off"}</small></>} />
          </BuilderSection>
          <BuilderSection number="05" title="Evaluators and guardrails">
            <label className="check-row"><input type="checkbox" checked={judge} onChange={(event) => setJudge(event.target.checked)} /><span><strong>Enable deterministic mock judge</strong><small>Correctness, groundedness and relevance are stored and marked as judge-based.</small></span></label>
            <label className="check-row"><input type="checkbox" checked={injectFailures} onChange={(event) => setInjectFailures(event.target.checked)} /><span><strong>Inject bounded provider failures</strong><small>Every seventh case fails after configured retries to verify partial-success handling.</small></span></label>
            <label className="field cost-field"><span>Maximum estimated cost (USD)</span><input type="number" min="0" step="0.01" value={maxCost} onChange={(event) => setMaxCost(event.target.value)} /></label>
          </BuilderSection>
        </div>
        <aside className="matrix-preview">
          <div><h2>Matrix preview</h2><p>Every selection is expanded before the run begins.</p></div>
          <dl>
            <div><dt>Models</dt><dd>{modelIds.length}</dd></div>
            <div><dt>Prompts</dt><dd>{promptIds.length}</dd></div>
            <div><dt>Retrieval configs</dt><dd>{retrievalIds.length}</dd></div>
            <div><dt>Cases</dt><dd>{dataset?.case_count ?? 0}</dd></div>
          </dl>
          <div className="matrix-equation">{modelIds.length} × {promptIds.length} × {retrievalIds.length} × {dataset?.case_count ?? 0}<strong>{matrixSize.toLocaleString()} generations</strong></div>
          <div className="workload-line"><span>Estimated workload</span><strong>{matrixSize ? `~${Math.max(1, Math.ceil(matrixSize / 360))} min at concurrency 6` : "—"}</strong></div>
          <div className="workload-line"><span>Estimated token cost</span><strong>{estimatedCost === null ? "unavailable" : formatMoney(estimatedCost)}</strong></div>
          <p className="fine-print">Cost is an estimate from selected snapshot pricing and assumed token workload. Final cost uses provider-reported or deterministic-mock token usage.</p>
          <button className="primary run-button" disabled={!ready} onClick={start}>{starting ? "Starting once…" : `Run ${matrixSize.toLocaleString()} generations`}</button>
        </aside>
      </div>
    </PageFrame>
  );
}

function BuilderSection({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return <section className="builder-section"><header><span>{number}</span><h2>{title}</h2></header><div>{children}</div></section>;
}

function ChoiceGrid<T extends { id: string }>({ items, selected, onToggle, render }: { items: T[]; selected: string[]; onToggle: (id: string) => void; render: (item: T) => React.ReactNode }) {
  return <div className="choice-list">{items.map((item) => <label key={item.id} className={selected.includes(item.id) ? "choice-row selected" : "choice-row"}><input type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} /><span>{render(item)}</span></label>)}</div>;
}
