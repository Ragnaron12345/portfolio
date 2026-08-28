import { useCallback, useEffect, useState } from "react"

import { api } from "../api/client"
import { Icon } from "../components/Icon"
import { DocumentPreview } from "../components/DocumentPreview"
import {
  Button,
  ConfidenceBreakdown,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusMark,
  ValidationList,
  formatDate,
  formatPercent,
  humanize,
} from "../components/Ui"
import type { ReviewDetail, ReviewSummary } from "../types"

type QueueTab = "pending" | "approved" | "rejected"

export function ReviewQueuePage() {
  const [tab, setTab] = useState<QueueTab>("pending")
  const [reviews, setReviews] = useState<ReviewSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ReviewDetail | null>(null)
  const [fields, setFields] = useState<Record<string, unknown>>({})
  const [notes, setNotes] = useState("")
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  const loadQueue = useCallback(async () => {
    setError("")
    try {
      const next = await api.reviews(tab)
      setReviews(next)
      setSelectedId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id || null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => { void loadQueue() }, [loadQueue])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let active = true
    setDetailLoading(true)
    void api.review(selectedId)
      .then((next) => {
        if (!active) return
        setDetail(next)
        setFields(structuredClone(next.document.structured_data || {}))
        setNotes(next.reviewer_notes || "")
      })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Unknown error") })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [selectedId])

  const act = async (action: "approve" | "reject" | "edit") => {
    if (!detail) return
    setBusy(action)
    setError("")
    setSuccess("")
    try {
      if (action === "approve") await api.approve(detail.id, notes)
      if (action === "reject") await api.reject(detail.id, notes)
      if (action === "edit") await api.editApprove(detail.id, fields, notes)
      setSuccess(action === "reject" ? "Document rejected and audit history updated." : "Decision recorded; document approved.")
      await loadQueue()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Decision failed")
    } finally {
      setBusy("")
    }
  }

  const rerunOcr = async () => {
    if (!detail) return
    setBusy("ocr")
    setError("")
    try {
      await api.rerunOcr(detail.document.id)
      const refreshed = await api.review(detail.id)
      setDetail(refreshed)
      setFields(structuredClone(refreshed.document.structured_data || {}))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "OCR rerun failed")
    } finally {
      setBusy("")
    }
  }

  const filtered = reviews.filter((review) => review.filename.toLowerCase().includes(query.toLowerCase()))

  if (loading) return <LoadingState label="Loading review queue" />
  if (error && !reviews.length) return <ErrorState message={error} onRetry={() => void loadQueue()} />

  return (
    <div className="page page-reviews">
      <PageHeader title="Review queue" />
      {error ? <ErrorState message={error} /> : null}
      {success ? <div className="success-banner"><Icon name="check" />{success}</div> : null}
      <section className="review-workspace">
        <div className="review-list-pane">
          <div className="queue-tabs" role="tablist">
            {(["pending", "approved", "rejected"] as QueueTab[]).map((value) => (
              <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? "active-tab" : ""} onClick={() => { setTab(value); setLoading(true) }}>
                {value === "pending" ? "Unresolved" : humanize(value)} {value === "pending" ? <span>{reviews.length}</span> : null}
              </button>
            ))}
          </div>
          <div className="filter-toolbar">
            <label className="search-field"><Icon name="search" /><input aria-label="Search review queue" placeholder="Search documents..." value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <button className="icon-button" aria-label="Refresh queue" onClick={() => void loadQueue()}><Icon name="refresh" /></button>
          </div>
          {filtered.length ? (
            <div className="table-scroll queue-table-wrap">
              <table className="data-table queue-table">
                <thead><tr><th>Document</th><th>Type</th><th>Confidence</th><th>Review reason</th><th>Received</th></tr></thead>
                <tbody>
                  {filtered.map((review) => (
                    <tr key={review.id} className={review.id === selectedId ? "selected-row" : ""} onClick={() => setSelectedId(review.id)}>
                      <td><span className="document-cell"><Icon name="documents" />{review.filename}</span></td>
                      <td>{humanize(review.document_type)}</td>
                      <td className="mono">{formatPercent(review.confidence)}</td>
                      <td>{review.reason}</td>
                      <td>{formatDate(review.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState title={`No ${tab} reviews`} message="The queue is empty for this decision state." />}
        </div>
        <aside className="review-detail-pane">
          {detailLoading ? <LoadingState label="Loading review evidence" /> : null}
          {!detailLoading && detail ? (
            <>
              <header className="review-detail-header"><h2>{detail.filename}</h2><StatusMark status={detail.status} /></header>
              <div className="review-evidence-grid">
                <section className="review-original">
                  <header><h3>Original document</h3><a href={api.fileUrl(detail.document.id)} target="_blank" rel="noreferrer">Open full size</a></header>
                  <DocumentPreview documentId={detail.document.id} filename={detail.filename} mimeType={detail.document.mime_type} />
                </section>
                <section className="field-editor">
                  <header><h3>Structured fields</h3><span>Schema-controlled</span></header>
                  <div className="field-editor-scroll">
                    {Object.entries(fields).map(([key, value]) => (
                      <EditableField key={key} name={key} value={value} onChange={(next) => setFields((current) => ({ ...current, [key]: next }))} />
                    ))}
                  </div>
                </section>
              </div>
              <div className="review-analysis-grid">
                <section><h3>Rule results</h3><ValidationList rules={detail.document.validation} /></section>
                <ConfidenceBreakdown confidence={detail.document.confidence} components={detail.document.confidence_breakdown.components} />
                <section className="history-section"><h3>Decision history</h3><History entries={detail.decision_history} /></section>
              </div>
              <label className="review-notes">Reviewer note<textarea value={notes} placeholder="Optional decision context" onChange={(event) => setNotes(event.target.value)} /></label>
              <footer className="review-actions">
                {detail.status === "pending" ? <Button variant="danger" busy={busy === "reject"} onClick={() => void act("reject")}>Reject</Button> : null}
                <Button busy={busy === "ocr"} onClick={() => void rerunOcr()}><Icon name="refresh" />Re-run OCR</Button>
                {detail.status === "pending" ? <Button busy={busy === "approve"} onClick={() => void act("approve")}>Approve unchanged</Button> : null}
                {detail.status === "pending" ? <Button variant="primary" busy={busy === "edit"} onClick={() => void act("edit")}><Icon name="check" />Edit and approve</Button> : null}
              </footer>
            </>
          ) : null}
          {!detailLoading && !detail ? <EmptyState title="Select a review" message="Choose a queue item to compare the source, fields, and validation evidence." /> : null}
        </aside>
      </section>
    </div>
  )
}

function EditableField({ name, value, onChange }: { name: string; value: unknown; onChange: (value: unknown) => void }) {
  if (Array.isArray(value) || (typeof value === "object" && value !== null)) {
    return <div className="complex-field"><span>{humanize(name)}</span><pre>{JSON.stringify(value, null, 2)}</pre></div>
  }
  const inputType = typeof value === "number" ? "number" : name.includes("date") ? "date" : "text"
  return (
    <label>{humanize(name)}<input type={inputType} step={inputType === "number" ? "0.01" : undefined} value={value === null ? "" : String(value)} onChange={(event) => onChange(inputType === "number" ? Number(event.target.value) : event.target.value || null)} /></label>
  )
}

function History({ entries }: { entries: Array<Record<string, string | null>> }) {
  if (!entries.length) return <p className="quiet-copy">No decision history yet.</p>
  return (
    <ol className="history-list">
      {entries.map((entry, index) => (
        <li key={`${entry.created_at}-${index}`}><span className="history-node" /><div><strong>{humanize(entry.action || "event")}</strong><p>{entry.reason || entry.notes || "Workflow state recorded."}</p><small>{entry.actor} · {entry.created_at ? formatDate(entry.created_at) : ""}</small></div></li>
      ))}
    </ol>
  )
}
