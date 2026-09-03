import type { MetricValue, RunStatus } from "../types";

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

export function formatMoney(value: number | null, digits = 4): string {
  if (value === null) return "unavailable";
  return `$${value.toFixed(digits)}`;
}

export function formatMetric(value: number | null, unit: string): string {
  if (value === null) return "unavailable";
  if (unit === "%") return `${(value * 100).toFixed(1)}%`;
  if (unit === "ms") return `${value.toFixed(1)} ms`;
  if (unit === "USD") return formatMoney(value, 5);
  if (unit === "/ 5") return `${value.toFixed(2)} / 5`;
  if (unit === "tokens") return `${Math.round(value).toLocaleString()} tokens`;
  return `${value.toFixed(2)} ${unit}`;
}

export function formatSample(metric: MetricValue | null): string {
  if (!metric) return "n=0";
  if (metric.numerator !== null && metric.denominator !== null && metric.unit === "%") {
    return `${metric.numerator}/${metric.denominator} · n=${metric.sample_count}`;
  }
  return `n=${metric.sample_count}`;
}

export function statusLabel(status: RunStatus): string {
  return {
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    completed_with_errors: "Completed with errors",
    failed: "Failed",
    cancelled: "Cancelled",
  }[status];
}
