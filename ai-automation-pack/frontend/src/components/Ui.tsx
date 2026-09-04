import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";

export function Button({
  variant = "secondary",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  return <button className={`button button--${variant} ${className}`.trim()} {...props}>{children}</button>;
}

export function StatusMark({ status, label }: { status: string; label?: string }) {
  const normalized = status.toLowerCase();
  const tone = normalized.includes("fail") || normalized.includes("reject") || normalized.includes("unhealthy")
    ? "danger"
    : normalized.includes("wait") || normalized.includes("review") || normalized.includes("warning") || normalized.includes("degraded")
      ? "warning"
      : normalized.includes("complete") || normalized.includes("success") || normalized.includes("approve") || normalized.includes("healthy") || normalized === "ok"
        ? "success"
        : normalized.includes("running") || normalized.includes("received")
          ? "active"
          : "neutral";
  return (
    <span className={`status-mark status-mark--${tone}`}>
      <span className="status-mark__dot" aria-hidden="true" />
      {label ?? humanize(status)}
    </span>
  );
}

export function RiskTag({ risk }: { risk: string }) {
  const tone = risk.toLowerCase() === "high" ? "danger" : risk.toLowerCase() === "medium" ? "warning" : "active";
  return <span className={`risk-tag risk-tag--${tone}`}>{humanize(risk)}</span>;
}

export function PageHeader({ title, action, subtitle }: { title: string; action?: ReactNode; subtitle?: string }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action ? <div className="page-header__actions">{action}</div> : null}
    </header>
  );
}

export function SectionHeader({ title, meta, action }: { title: string; meta?: string; action?: ReactNode }) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        {meta ? <span>{meta}</span> : null}
      </div>
      {action}
    </div>
  );
}

export function LoadingState({ label = "Loading operational data" }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="loading-state__pulse" />
      <span>{label}</span>
    </div>
  );
}

export function LoadingRows({ count = 5 }: { count?: number }) {
  return (
    <div className="loading-rows" role="status" aria-label="Loading data">
      {Array.from({ length: count }, (_, index) => (
        <div className="loading-row" key={index}>
          <span /><span /><span /><span />
        </div>
      ))}
    </div>
  );
}

export function ErrorBanner({ error, onRetry, title = "Could not load this view" }: { error: Error; onRetry?: () => void; title?: string }) {
  return (
    <div className="error-banner" role="alert">
      <Icon name="warning" />
      <div><strong>{title}</strong><span>{error.message}</span></div>
      {onRetry ? <Button variant="secondary" onClick={onRetry}><Icon name="refresh" /> Retry</Button> : null}
    </div>
  );
}

export function EmptyState({ title, body, icon = "file" }: { title: string; body: string; icon?: "file" | "reviews" | "systems" | "audit" | "executions" }) {
  return (
    <div className="empty-state">
      <Icon name={icon} />
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}

export function RefreshMeta({ lastUpdated, refreshing, onRefresh }: { lastUpdated: Date | null; refreshing: boolean; onRefresh: () => void }) {
  return (
    <div className="refresh-meta" aria-live="polite">
      <span className="live-dot" />
      <span><strong>{refreshing ? "Updating…" : "Auto-updating every 5s"}</strong>{lastUpdated ? ` · Last updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}</span>
      <button className="icon-button" onClick={onRefresh} aria-label="Refresh now"><Icon name="refresh" /></button>
    </div>
  );
}

export function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function safeDisplay(value: unknown): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if ((trimmed.startsWith("{") || trimmed.startsWith("[")) && trimmed.length > 160) {
      return "Structured content was withheld because it could not be rendered safely.";
    }
    return trimmed;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "Not provided";
}

export function ReadableData({ value, empty = "No input recorded." }: { value: Record<string, unknown>; empty?: string }) {
  const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined);
  if (!entries.length) return <p className="muted-copy">{empty}</p>;
  return (
    <dl className="readable-data">
      {entries.map(([key, item]) => {
        const display = Array.isArray(item)
          ? item.map(safeDisplay).filter((entry) => entry !== "Not provided").join(" · ") || "Not provided"
          : safeDisplay(item);
        return <div key={key}><dt>{humanize(key)}</dt><dd>{display}</dd></div>;
      })}
    </dl>
  );
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined) return "—";
  if (milliseconds < 1_000) return `${Math.round(milliseconds)} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1_000).toFixed(milliseconds >= 10_000 ? 1 : 2)} s`;
  const minutes = Math.floor(milliseconds / 60_000);
  return `${minutes}m ${Math.round((milliseconds % 60_000) / 1_000)}s`;
}

export function formatTime(value: string | null | undefined, includeDate = false): string {
  if (!value || Date.parse(value) === 0 || Number.isNaN(Date.parse(value))) return "—";
  return new Date(value).toLocaleString([], includeDate
    ? { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }
    : { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatPercent(value: number, decimals = 0): string {
  return `${value.toFixed(decimals)}%`;
}
