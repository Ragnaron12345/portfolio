import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export function PageHeader({
  title,
  actions,
  meta,
}: {
  title: string;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {meta ? <div className="page-header__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  icon?: IconName;
};

export function Button({ variant = "secondary", icon, children, className = "", ...props }: ButtonProps) {
  const accessibleLabel = props["aria-label"] ?? (typeof children === "string" ? children : undefined);
  return (
    <button className={`button button--${variant} ${className}`.trim()} aria-label={accessibleLabel} {...props}>
      {icon ? <Icon name={icon} /> : null}
      <span>{children}</span>
    </button>
  );
}

export function StatusMark({
  tone,
  children,
}: {
  tone: "success" | "warning" | "danger" | "info" | "neutral";
  children: ReactNode;
}) {
  return <span className={`status-mark status-mark--${tone}`}>{children}</span>;
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="loading-rows" aria-label="Loading" aria-live="polite">
      {Array.from({ length: rows }, (_, index) => <span key={index} />)}
    </div>
  );
}

export function ErrorBanner({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <Icon name="warning" />
      <span>{message}</span>
      {retry ? <Button variant="ghost" onClick={retry}>Retry</Button> : null}
    </div>
  );
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__rule" />
      <h2>{title}</h2>
      <p>{message}</p>
      {action}
    </div>
  );
}

export function formatNumber(value: number, maximumFractionDigits = 0) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(value);
}

export function formatPercent(value: number) {
  const normalized = value <= 1 ? value * 100 : value;
  return `${normalized.toFixed(normalized < 10 ? 1 : 0)}%`;
}

export function formatDuration(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10_000 ? 1 : 2)} s` : `${Math.round(ms)} ms`;
}

export function formatMoney(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 6 }).format(value);
}
