import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Dataset, DatasetCase } from "../types";
import { StatePanel } from "../components/StatePanel";
import { PageFrame, PageHeader } from "./OverviewPage";

export function DatasetBrowserPage() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [selectedCase, setSelectedCase] = useState<DatasetCase | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Dataset[]>("/datasets").then(async (items) => { setDatasets(items); if (items[0]) { const full = await api<Dataset>(`/datasets/${items[0].id}`); setSelected(full); setSelectedCase(full.cases?.[0] ?? null); } }).catch((reason: Error) => setError(reason.message)); }, []);
  const categories = useMemo(() => [...new Set(selected?.cases?.map((item) => String(item.metadata.category)) ?? [])], [selected]);
  const filtered = useMemo(() => selected?.cases?.filter((item) => (!category || item.metadata.category === category) && (!query || `${item.id} ${item.input}`.toLowerCase().includes(query.toLowerCase()))) ?? [], [category, query, selected]);
  async function chooseDataset(id: string) { const full = await api<Dataset>(`/datasets/${id}`); setSelected(full); setSelectedCase(full.cases?.[0] ?? null); }
  if (error) return <PageFrame><StatePanel kind="error" title="Dataset browser unavailable">{error}</StatePanel></PageFrame>;
  if (!datasets || !selected) return <PageFrame><StatePanel kind="loading" title="Loading versioned datasets" /></PageFrame>;
  if (!datasets.length) return <PageFrame><StatePanel kind="empty" title="No datasets registered" /></PageFrame>;
  return <PageFrame>
    <PageHeader title="Dataset browser" subtitle="Versioned JSONL cases with reproducible content hashes" actions={<select value={selected.id} onChange={(event) => void chooseDataset(event.target.value)}>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select>} />
    <div className="dataset-meta"><span><b>{selected.case_count}</b> cases</span><span>SHA-256 <code>{selected.content_hash}</code></span><span>created {new Date(selected.created_at).toLocaleString()}</span></div>
    <div className="filter-bar"><label>Search<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Case ID or question" /></label><label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{categories.map((item) => <option key={item}>{item.replaceAll("_", " ")}</option>)}</select></label></div>
    <div className="dataset-layout"><section className="case-list"><header>{filtered.length} cases</header>{filtered.map((item) => <button key={item.id} className={selectedCase?.id === item.id ? "selected" : ""} onClick={() => setSelectedCase(item)}><strong>{item.id}</strong><span>{String(item.metadata.category).replaceAll("_", " ")}</span><p>{item.input}</p></button>)}</section>{selectedCase ? <article className="case-json"><header><div><span>{selectedCase.id}</span><h2>{selectedCase.input}</h2></div><em>{String(selectedCase.metadata.difficulty)}</em></header><JsonField label="Reference answer" value={selectedCase.reference_answer} /><JsonField label="Expected keywords" value={selectedCase.expected_keywords} /><JsonField label="Forbidden claims" value={selectedCase.forbidden_claims} /><JsonField label="Context" value={selectedCase.context} /><JsonField label="Expected citations" value={selectedCase.expected_citations} /><JsonField label="Metadata" value={selectedCase.metadata} /></article> : null}</div>
  </PageFrame>;
}

function JsonField({ label, value }: { label: string; value: unknown }) { return <section><h3>{label}</h3><pre>{JSON.stringify(value, null, 2)}</pre></section>; }
