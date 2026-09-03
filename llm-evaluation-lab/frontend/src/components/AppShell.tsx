import type { PropsWithChildren } from "react";
import { Icon } from "./Icon";
import { navigate } from "../lib/router";

const navigation = [
  { label: "Overview", path: "/overview", icon: "overview" as const },
  { label: "Experiment builder", path: "/experiments/new", icon: "experiment" as const },
  { label: "Runs", path: "/runs", icon: "runs" as const },
  { label: "Failures", path: "/failures", icon: "failures" as const },
  { label: "Prompt registry", path: "/prompts", icon: "prompts" as const },
  { label: "Datasets", path: "/datasets", icon: "datasets" as const },
  { label: "RAG inspector", path: "/rag", icon: "rag" as const },
];

function isActive(current: string, path: string): boolean {
  if (path === "/runs") return current.startsWith("/runs");
  return current.startsWith(path);
}

export function AppShell({ currentPath, children }: PropsWithChildren<{ currentPath: string }>) {
  return (
    <div className="app-shell">
      <aside className="side-rail">
        <button className="brand" onClick={() => navigate("/overview")} aria-label="EvalForge overview">
          <span className="brand-mark" aria-hidden="true"><i /><i /></span>
          <span>EvalForge</span>
        </button>
        <nav aria-label="Primary navigation">
          {navigation.map((item) => (
            <button
              key={item.path}
              className={isActive(currentPath, item.path) ? "nav-item active" : "nav-item"}
              onClick={() => navigate(item.path)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="rail-footer">
          <div className="team-avatar">EF</div>
          <div><strong>Evaluation Lab</strong><span>Local workspace</span></div>
        </div>
      </aside>
      <div className="workspace">
        <header className="top-bar">
          <span>AI Engineering</span>
          <div className="top-actions">
            <a href="/api/v1/docs" target="_blank" rel="noreferrer">API</a>
            <button className="primary compact" onClick={() => navigate("/experiments/new")}>New experiment <span>⌘ N</span></button>
          </div>
        </header>
        <main>{children}</main>
      </div>
    </div>
  );
}
