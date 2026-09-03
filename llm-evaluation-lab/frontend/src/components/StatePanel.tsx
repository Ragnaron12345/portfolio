import type { ReactNode } from "react";

export function StatePanel({ kind, title, children, action }: { kind: "loading" | "empty" | "error"; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <section className={`state-panel ${kind}`} role={kind === "error" ? "alert" : "status"} aria-live="polite">
      <span className="state-symbol" aria-hidden="true">{kind === "loading" ? "◌" : kind === "error" ? "!" : "∅"}</span>
      <div><h2>{title}</h2>{children ? <p>{children}</p> : null}{action}</div>
    </section>
  );
}
