import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { PromptVersion } from "../types";
import { StatePanel } from "../components/StatePanel";
import { PageFrame, PageHeader } from "./OverviewPage";

export function PromptRegistryPage() {
  const [items, setItems] = useState<PromptVersion[] | null>(null);
  const [leftId, setLeftId] = useState("");
  const [rightId, setRightId] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<PromptVersion[]>("/prompts").then((data) => { setItems(data); setLeftId(data[0]?.id ?? ""); setRightId(data[1]?.id ?? data[0]?.id ?? ""); }).catch((reason: Error) => setError(reason.message)); }, []);
  const left = items?.find((item) => item.id === leftId);
  const right = items?.find((item) => item.id === rightId);
  const diff = useMemo(() => lineDiff(left?.system_prompt ?? "", right?.system_prompt ?? ""), [left, right]);
  if (error) return <PageFrame><StatePanel kind="error" title="Prompt registry unavailable">{error}</StatePanel></PageFrame>;
  if (!items) return <PageFrame><StatePanel kind="loading" title="Loading prompt versions" /></PageFrame>;
  if (!items.length) return <PageFrame><StatePanel kind="empty" title="No prompt versions registered" /></PageFrame>;
  return <PageFrame>
    <PageHeader title="Prompt registry" subtitle="Exact, versioned prompts with an inspectable diff" />
    <div className="registry-layout">
      <aside className="version-list">{items.map((item) => <button key={item.id} className={rightId === item.id ? "selected" : ""} onClick={() => setRightId(item.id)}><span><strong>{item.name}</strong><em>v{item.semantic_version}</em></span><small>{new Date(item.created_at).toLocaleDateString()}</small><p>{item.tags.join(" · ")}</p></button>)}</aside>
      <section className="prompt-detail">
        <div className="diff-selectors"><label>Compare<select value={leftId} onChange={(event) => setLeftId(event.target.value)}>{items.map((item) => <option key={item.id} value={item.id}>v{item.semantic_version}</option>)}</select></label><span>with</span><label><span className="sr-only">Candidate version</span><select value={rightId} onChange={(event) => setRightId(event.target.value)}>{items.map((item) => <option key={item.id} value={item.id}>v{item.semantic_version}</option>)}</select></label></div>
        <h2>System prompt diff</h2><div className="code-diff">{diff.map((line, index) => <code key={`${line.kind}-${index}`} className={line.kind}><span>{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span>{line.text}</code>)}</div>
        <div className="prompt-columns"><div><h3>System prompt · v{left?.semantic_version}</h3><pre>{left?.system_prompt}</pre><h3>User template</h3><pre>{left?.user_template}</pre></div><div><h3>System prompt · v{right?.semantic_version}</h3><pre>{right?.system_prompt}</pre><h3>User template</h3><pre>{right?.user_template}</pre></div></div>
      </section>
    </div>
  </PageFrame>;
}

export function lineDiff(left: string, right: string): Array<{ kind: "same" | "removed" | "added"; text: string }> {
  if (left === right) return left.split("\n").map((text) => ({ kind: "same", text }));
  return [
    ...left.split("\n").map((text) => ({ kind: "removed" as const, text })),
    ...right.split("\n").map((text) => ({ kind: "added" as const, text })),
  ];
}
