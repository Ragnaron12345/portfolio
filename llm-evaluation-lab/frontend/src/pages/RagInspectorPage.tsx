import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { navigate } from "../lib/router";
import type { FailureCase, RunSummary } from "../types";
import { StatePanel } from "../components/StatePanel";
import { PageFrame, PageHeader } from "./OverviewPage";

export function RagInspectorPage({ initialRunId }: { initialRunId: string | null }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState(initialRunId ?? "");
  const [results, setResults] = useState<FailureCase[] | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<RunSummary[]>("/runs").then((items) => { setRuns(items); if (!initialRunId && items[0]) setRunId(items[0].id); }).catch((reason: Error) => setError(reason.message)); }, [initialRunId]);
  useEffect(() => { if (!runId) return; api<{ items: FailureCase[] }>(`/runs/${runId}/results?limit=500`).then((payload) => { const withChunks = payload.items.filter((item) => item.retrieved_chunks.length); setResults(withChunks); setSelectedId((current) => current || withChunks[0]?.id || ""); }).catch((reason: Error) => setError(reason.message)); }, [runId]);
  const grouped = useMemo(() => {
    const map = new Map<string, FailureCase>();
    for (const item of results ?? []) if (!map.has(item.case_id)) map.set(item.case_id, item);
    return [...map.values()];
  }, [results]);
  const selected = results?.find((item) => item.id === selectedId) ?? grouped[0];
  if (error) return <PageFrame><StatePanel kind="error" title="RAG inspector unavailable">{error}</StatePanel></PageFrame>;
  if (!results) return <PageFrame><StatePanel kind="loading" title="Loading retrieved evidence" /></PageFrame>;
  if (!results.length) return <PageFrame><StatePanel kind="empty" title="No retrieved chunks for this run">Choose a run that includes context-bearing cases.</StatePanel></PageFrame>;
  return <PageFrame>
    <PageHeader title="RAG inspector" subtitle="Rank, relevance score, source identity and expected-source hit/miss" actions={<select value={runId} onChange={(event) => { setRunId(event.target.value); navigate(`/rag?runId=${event.target.value}`); }}>{runs.map((item) => <option key={item.id} value={item.id}>{item.experiment_name} · {item.id}</option>)}</select>} />
    <div className="rag-layout"><aside className="rag-cases">{grouped.map((item) => <button key={item.case_id} className={selected?.case_id === item.case_id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><strong>{item.case_id}</strong><span>{item.category.replaceAll("_", " ")}</span><p>{item.input}</p></button>)}</aside>{selected ? <article className="rag-detail"><header><div><span>{selected.case_id}</span><h2>{selected.input}</h2></div><select value={selected.id} onChange={(event) => setSelectedId(event.target.value)} aria-label="Configuration result">{results.filter((item) => item.case_id === selected.case_id).map((item) => <option key={item.id} value={item.id}>{item.combination_key}</option>)}</select></header><div className="rag-answer"><span>Model output</span><p>{selected.output ?? "No output returned"}</p></div><div className="chunk-list">{selected.retrieved_chunks.map((chunk) => <section key={`${chunk.rank}-${chunk.source_id}`} className={chunk.expected_source ? "hit" : "miss"}><div><span className="rank">#{chunk.rank}</span><strong>{chunk.source_id}</strong><b>{chunk.score.toFixed(3)}</b><em>{chunk.expected_source ? "expected-source hit" : "expected-source miss"}</em></div><p>{chunk.text}</p></section>)}</div></article> : null}</div>
  </PageFrame>;
}
