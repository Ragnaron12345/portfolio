import type { ReactNode } from "react"

import { Icon } from "./Icon"
import type { Stage, ValidationRule } from "../types"

export function Button({
  children,
  variant = "secondary",
  busy = false,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger"; busy?: boolean }) {
  return (
    <button className={`button button-${variant}`} disabled={busy || props.disabled} {...props}>
      {busy ? <span className="button-progress" aria-hidden="true" /> : null}
      {children}
    </button>
  )
}

export function StatusMark({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const kind = normalized.includes("accept") || normalized.includes("approv") || normalized === "completed" || normalized === "success" || normalized === "pass"
    ? "success"
    : normalized.includes("review") || normalized === "warning" || normalized === "pending"
      ? "warning"
      : normalized.includes("fail") || normalized.includes("reject")
        ? "danger"
        : "neutral"
  const icon = kind === "success" ? "check" : kind === "warning" ? "warning" : kind === "danger" ? "error" : "documents"
  return (
    <span className={`status-mark status-${kind}`}>
      <Icon name={icon} size={15} />
      {humanize(status)}
    </span>
  )
}

export function PageHeader({ title, action }: { title: string; action?: ReactNode }) {
  return <header className="page-header"><h1>{title}</h1>{action}</header>
}

export function LoadingState({ label = "Loading workspace" }: { label?: string }) {
  return <div className="state-view" role="status"><span className="loading-line" />{label}</div>
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <Icon name="error" />
      <span><strong>Could not load this workspace.</strong>{message}</span>
      {onRetry ? <Button onClick={onRetry}>Retry</Button> : null}
    </div>
  )
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return <div className="empty-state"><Icon name="documents" size={30} /><strong>{title}</strong><span>{message}</span></div>
}

export function PipelineTrace({ stages }: { stages: Stage[] }) {
  return (
    <ol className="pipeline-trace">
      {stages.map((stage, index) => (
        <li key={`${stage.name}-${index}`} className={`trace-stage trace-${stage.status}`}>
          <span className="trace-node">{index + 1}</span>
          <span className="trace-copy">
            <strong>{humanize(stage.name)}</strong>
            <small>{stage.summary}</small>
            {stage.error ? <em>{stage.error}</em> : null}
          </span>
          <span className="mono trace-duration">{stage.duration_ms > 0 ? `${formatNumber(stage.duration_ms)} ms` : "—"}</span>
        </li>
      ))}
    </ol>
  )
}

export function ValidationList({ rules }: { rules: ValidationRule[] }) {
  if (!rules.length) return <EmptyState title="No validation rules" message="A supported schema was not selected." />
  return (
    <div className="validation-list">
      {rules.map((rule) => (
        <div key={rule.rule_id} className={`validation-row validation-${rule.status}`}>
          <StatusMark status={rule.status} />
          <span><strong>{rule.name}</strong><small>{rule.message}</small></span>
        </div>
      ))}
    </div>
  )
}

export function ConfidenceBreakdown({
  confidence,
  components = {},
  definition,
}: {
  confidence: number
  components?: Record<string, number>
  definition?: string
}) {
  return (
    <section className="confidence-section">
      <div className="confidence-overall"><span>Overall confidence</span><strong>{formatPercent(confidence)}</strong></div>
      {definition ? <p className="definition-copy">{definition}</p> : null}
      <div className="confidence-bars">
        {Object.entries(components).map(([key, value]) => (
          <div className="confidence-row" key={key}>
            <span>{humanize(key)}</span>
            <span className="confidence-track"><i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></span>
            <span className="mono">{formatPercent(value)}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

export function humanize(value: string) {
  return value.replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase())
}

export function formatPercent(value: number) {
  return `${(value * 100).toFixed(value * 100 % 1 === 0 ? 0 : 1)}%`
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
}
