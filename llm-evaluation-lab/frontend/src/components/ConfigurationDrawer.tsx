import type { ExactConfiguration } from "../types";
import { Icon } from "./Icon";

export function ConfigurationDrawer({ configuration, onClose }: { configuration: ExactConfiguration; onClose: () => void }) {
  const { dataset, model, prompt, retrieval, evaluator_config: evaluator, git_commit: gitCommit, timestamp } = configuration;
  return (
    <aside className="config-drawer" aria-label="Immutable configuration">
      <header><div><h2>Configuration</h2><p>Immutable snapshot</p></div><button aria-label="Close configuration" onClick={onClose}><Icon name="close" /></button></header>
      <div className="immutability-note">This historical configuration cannot be changed.</div>
      <ConfigBlock label="Dataset"><strong>{String(dataset.name)}</strong><span>v{String(dataset.version)}</span><code>{String(dataset.hash)}</code></ConfigBlock>
      <ConfigBlock label="Provider / model"><strong>{model.provider} / {model.model}</strong><span>temperature {model.temperature} · max {model.max_tokens}</span><span>timeout {model.timeout_seconds}s · retries {model.retries}</span></ConfigBlock>
      <ConfigBlock label="Prompt version"><strong>{prompt.name} v{prompt.semantic_version}</strong><code>{prompt.id}</code><details><summary>View exact prompts</summary><span>System</span><pre>{prompt.system_prompt}</pre><span>User template</span><pre>{prompt.user_template}</pre></details></ConfigBlock>
      <ConfigBlock label="Retrieval (RAG)"><strong>{retrieval.name}</strong><span>{retrieval.mode} · top-k {retrieval.top_k}</span><span>chunk {retrieval.chunk_size} · overlap {retrieval.overlap}</span><span>reranker {retrieval.reranker_enabled ? "enabled" : "disabled"}</span></ConfigBlock>
      <ConfigBlock label="Evaluator"><pre>{JSON.stringify(evaluator, null, 2)}</pre></ConfigBlock>
      <ConfigBlock label="Git commit"><code>{gitCommit ?? "unavailable"}</code></ConfigBlock>
      <ConfigBlock label="Snapshot created"><span>{new Date(timestamp).toLocaleString()}</span></ConfigBlock>
    </aside>
  );
}

function ConfigBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return <section className="config-block"><span className="config-label">{label}</span>{children}</section>;
}
