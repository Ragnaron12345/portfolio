import { useCallback, useEffect, useState } from "react"

import { api } from "../api/client"
import { Icon } from "../components/Icon"
import { Button, EmptyState, ErrorState, LoadingState, PageHeader, StatusMark, formatDate, formatNumber } from "../components/Ui"
import type { EvaluationDetail, EvaluationMetric, EvaluationSummary } from "../types"

const STORAGE_KEY = "docintel:selected-evaluation:v1"

function loadStoredRun(): string | null {
  try { return window.localStorage.getItem(STORAGE_KEY) } catch { return null }
}

function storeRun(id: string) {
  try { window.localStorage.setItem(STORAGE_KEY, id) } catch { /* storage can be unavailable */ }
}

export function EvaluationsPage() {
  const [runs, setRuns] = useState<EvaluationSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(() => loadStoredRun())
  const [detail, setDetail] = useState<EvaluationDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")

  const loadRuns = useCallback(async () => {
    setError("")
    try {
      const nextRuns = await api.evaluationRuns()
      setRuns(nextRuns)
      setSelectedId((current) => {
        const next = current && nextRuns.some((run) => run.id === current) ? current : nextRuns[0]?.id || null
        if (next) storeRun(next)
        return next
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadRuns() }, [loadRuns])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let active = true
    storeRun(selectedId)
    void api.evaluation(selectedId)
      .then((next) => { if (active) setDetail(next) })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Unknown error") })
    return () => { active = false }
  }, [selectedId])

  const runEvaluation = async () => {
    setRunning(true)
    setError("")
    try {
      const next = await api.runEvaluation()
      await loadRuns()
      setSelectedId(next.id)
      setDetail(next)
      storeRun(next.id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Evaluation failed")
    } finally {
      setRunning(false)
    }
  }

  if (loading) return <LoadingState label="Loading evaluation history" />
  if (error && !runs.length) return <ErrorState message={error} onRetry={() => void loadRuns()} />

  return (
    <div className="page page-evaluations">
      <PageHeader title="Evaluations" action={<Button variant="primary" busy={running} onClick={() => void runEvaluation()}><Icon name="arrow" />Run evaluation</Button>} />
      {error ? <ErrorState message={error} /> : null}
      <section className="evaluation-workspace">
        <aside className="runs-pane">
          <h2>Historical runs</h2>
          {runs.length ? <table className="data-table runs-table"><thead><tr><th>Run name</th><th>Status</th><th>Created</th></tr></thead><tbody>{runs.map((run) => (
            <tr key={run.id} className={run.id === selectedId ? "selected-row" : ""} onClick={() => setSelectedId(run.id)}>
              <td><strong>{run.name}</strong><small>{run.dataset_size} documents</small></td><td><StatusMark status={run.status} /></td><td>{formatDate(run.started_at)}</td>
            </tr>
          ))}</tbody></table> : <EmptyState title="No evaluation runs" message="Run the versioned synthetic dataset to create the first comparison." />}
        </aside>
        <div className="evaluation-detail">
          {detail ? (
            <>
              <header className="eval-summary"><div><h2>{detail.name}</h2><StatusMark status={detail.status} /></div><span>Dataset: {detail.config.dataset} · {detail.dataset_size} documents</span><small>Created {formatDate(detail.started_at)} · SHA-256 {detail.config.dataset_sha256.slice(0, 12)}…</small></header>
              <section className="config-comparison"><div><h3>Baseline</h3><p>{detail.config.baseline}</p></div><div><h3>Improved</h3><p>{detail.config.improved}</p></div></section>
              <div className="table-scroll metrics-table-wrap">
                <table className="data-table metrics-table"><thead><tr><th>Metric</th><th>Baseline</th><th>Improved</th><th>Delta</th></tr></thead><tbody>{detail.metrics.map((metric) => <MetricRow key={metric.key} metric={metric} />)}</tbody></table>
              </div>
              <section className="evaluation-findings">
                <FindingTable title="Most improved cases" records={detail.details.most_improved} />
                <FindingTable title="Remaining failures" records={detail.details.remaining_failures} />
              </section>
              <footer className="methodology-note">{detail.details.methodology}</footer>
            </>
          ) : <LoadingState label="Loading selected evaluation" />}
        </div>
      </section>
    </div>
  )
}

function MetricRow({ metric }: { metric: EvaluationMetric }) {
  const format = (value: number) => {
    if (metric.unit === "percent") return `${value.toFixed(1)}%`
    if (metric.unit === "ms") return `${formatNumber(value)} ms`
    return `$${value.toFixed(4)}`
  }
  const delta = metric.unit === "percent"
    ? `${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(1)} pp`
    : metric.unit === "ms"
      ? `${metric.delta >= 0 ? "+" : "−"}${formatNumber(Math.abs(metric.delta))} ms`
      : `${metric.delta >= 0 ? "+" : "−"}$${Math.abs(metric.delta).toFixed(4)}`
  return (
    <tr><td><strong>{metric.label}</strong><small>{metric.definition}</small></td><td className="mono">{format(metric.baseline)}</td><td className="mono improved-value">{format(metric.improved)}</td><td className={`mono ${metric.improvement >= 0 ? "positive-delta" : "negative-delta"}`}>{delta}</td></tr>
  )
}

function FindingTable({ title, records }: { title: string; records: Array<Record<string, string>> }) {
  const keys = records.length ? Object.keys(records[0]) : []
  return (
    <section className="finding-table"><h3>{title}</h3>{records.length ? <table className="data-table"><thead><tr>{keys.map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{records.map((record, index) => <tr key={`${title}-${index}`}>{keys.map((key) => <td key={key}>{record[key]}</td>)}</tr>)}</tbody></table> : <p className="quiet-copy">No cases in this group.</p>}</section>
  )
}
