import { useCallback, useEffect, useState } from "react"

import { api } from "../api/client"
import type { PageKey } from "../components/AppShell"
import { Icon } from "../components/Icon"
import { Button, ErrorState, LoadingState, PageHeader, StatusMark, formatDate, formatNumber, humanize } from "../components/Ui"
import type { Metrics } from "../types"

export function OverviewPage({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    setError("")
    try {
      setMetrics(await api.metrics())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unknown error")
    }
  }, [])

  useEffect(() => { void load() }, [load])

  if (error) return <ErrorState message={error} onRetry={() => void load()} />
  if (!metrics) return <LoadingState label="Loading operational metrics" />

  const primaryMetrics = [
    ["Documents processed", metrics.documents_processed],
    ["Auto-accept rate", metrics.auto_accept_rate],
    ["Review rate", metrics.review_rate],
    ["Failed rate", metrics.failed_processing_rate],
    ["Average latency", metrics.average_latency],
    ["p95 latency", metrics.p95_latency],
  ] as const

  return (
    <div className="page page-overview">
      <PageHeader
        title="Operations overview"
        action={<Button variant="primary" onClick={() => onNavigate("documents")}><Icon name="upload" />Upload document</Button>}
      />
      <section className="metric-strip metric-strip-six" aria-label="Pipeline metrics">
        {primaryMetrics.map(([label, metric]) => (
          <div className="metric-cell" key={label} title={metric.definition}>
            <span>{label}</span>
            <strong className="mono">{formatNumber(metric.value)} <small>{metric.unit}</small></strong>
            <p>{metric.definition}</p>
          </div>
        ))}
      </section>
      <div className="overview-grid">
        <section className="open-section distribution-section">
          <header><h2>Document type distribution</h2><span>{metrics.documents_processed.value} total</span></header>
          <div className="distribution-bars">
            {Object.entries(metrics.document_type_distribution).map(([type, count]) => (
              <div key={type} className="distribution-row">
                <span>{humanize(type)}</span>
                <span className="distribution-track"><i style={{ width: `${count / Math.max(1, metrics.documents_processed.value) * 100}%` }} /></span>
                <strong className="mono">{count}</strong>
              </div>
            ))}
          </div>
        </section>
        <section className="open-section failure-section">
          <header><h2>Common validation exceptions</h2><span>Unresolved signals</span></header>
          {metrics.common_validation_failures.length ? (
            <ol className="ranked-list">
              {metrics.common_validation_failures.map((item, index) => (
                <li key={item.name}><span className="mono">{String(index + 1).padStart(2, "0")}</span><strong>{item.name}</strong><em>{item.count} document(s)</em></li>
              ))}
            </ol>
          ) : <p className="quiet-copy">No validation exceptions are currently recorded.</p>}
        </section>
      </div>
      <section className="table-section recent-section">
        <header className="section-header"><h2>Recent activity</h2><button className="text-action" onClick={() => onNavigate("documents")}>View all <Icon name="arrow" size={15} /></button></header>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Document</th><th>Type</th><th>Status</th><th>Confidence</th><th>Latency</th><th>Received</th></tr></thead>
            <tbody>
              {metrics.recent_activity.map((document) => (
                <tr key={document.id} onClick={() => onNavigate("documents")}>
                  <td><span className="document-cell"><Icon name="documents" />{document.filename}</span></td>
                  <td>{humanize(document.document_type)}</td>
                  <td><StatusMark status={document.status} /></td>
                  <td className="mono">{document.confidence ? `${Math.round(document.confidence * 100)}%` : "—"}</td>
                  <td className="mono">{formatNumber(document.total_latency_ms)} ms</td>
                  <td>{formatDate(document.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
