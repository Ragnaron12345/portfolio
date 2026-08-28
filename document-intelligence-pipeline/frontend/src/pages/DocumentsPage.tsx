import { useCallback, useEffect, useRef, useState } from "react"

import { api, uploadDocument } from "../api/client"
import { Icon } from "../components/Icon"
import { DocumentPreview } from "../components/DocumentPreview"
import {
  Button,
  ConfidenceBreakdown,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  PipelineTrace,
  StatusMark,
  ValidationList,
  formatDate,
  formatNumber,
  formatPercent,
  humanize,
} from "../components/Ui"
import type { DocumentDetail, DocumentSummary } from "../types"

type DetailTab = "original" | "text" | "structured" | "validation"

export function DocumentsPage({ onOpenReview }: { onOpenReview: () => void }) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DocumentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState("")
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [typeFilter, setTypeFilter] = useState("all")
  const [tab, setTab] = useState<DetailTab>("validation")
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState("")
  const [busyAction, setBusyAction] = useState("")
  const fileInput = useRef<HTMLInputElement>(null)

  const loadDocuments = useCallback(async () => {
    setError("")
    try {
      const nextDocuments = await api.documents()
      setDocuments(nextDocuments)
      setSelectedId((current) => current && nextDocuments.some((item) => item.id === current) ? current : nextDocuments[0]?.id || null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadDocuments() }, [loadDocuments])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let active = true
    setDetailLoading(true)
    void api.document(selectedId)
      .then((nextDetail) => { if (active) setDetail(nextDetail) })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Unknown error") })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [selectedId])

  const filtered = documents.filter((document) => {
    const matchesQuery = document.filename.toLowerCase().includes(query.toLowerCase())
    const matchesStatus = statusFilter === "all" || document.status === statusFilter
    const matchesType = typeFilter === "all" || document.document_type === typeFilter
    return matchesQuery && matchesStatus && matchesType
  })

  const upload = async (file: File) => {
    setUploadError("")
    setUploadProgress(0)
    try {
      const uploaded = await uploadDocument(file, setUploadProgress)
      await loadDocuments()
      setSelectedId(uploaded.id)
      setDetail(uploaded)
      setUploadOpen(false)
    } catch (reason) {
      setUploadError(reason instanceof Error ? reason.message : "Upload failed")
    } finally {
      setUploadProgress(null)
    }
  }

  const rerun = async (mode: "retry" | "ocr") => {
    if (!detail) return
    setBusyAction(mode)
    setError("")
    try {
      const next = mode === "retry" ? await api.retry(detail.id) : await api.rerunOcr(detail.id)
      setDetail(next)
      await loadDocuments()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed")
    } finally {
      setBusyAction("")
    }
  }

  if (loading) return <LoadingState label="Loading document workspace" />
  if (error && !documents.length) return <ErrorState message={error} onRetry={() => void loadDocuments()} />

  return (
    <div className="page page-documents">
      <PageHeader
        title="Documents"
        action={<Button variant="primary" onClick={() => setUploadOpen(true)}><Icon name="upload" />Upload document</Button>}
      />
      {error ? <ErrorState message={error} onRetry={() => void loadDocuments()} /> : null}
      <section className="document-workspace">
        <div className="document-list-pane">
          <DocumentMetricStrip documents={documents} />
          <div className="filter-toolbar">
            <label className="search-field"><Icon name="search" /><input aria-label="Search documents" placeholder="Search documents..." value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <label>Type<select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">All</option><option value="invoice">Invoice</option><option value="bank_statement">Bank statement</option><option value="customer_application">Application</option><option value="unknown">Unknown</option></select></label>
            <label>Status<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All</option><option value="accepted">Accepted</option><option value="needs_review">Needs review</option><option value="failed">Failed</option></select></label>
            <button className="icon-button" aria-label="Refresh documents" onClick={() => void loadDocuments()}><Icon name="refresh" /></button>
          </div>
          {filtered.length ? (
            <div className="table-scroll document-table-wrap">
              <table className="data-table document-table">
                <thead><tr><th>Document</th><th>Type</th><th>Status</th><th>Confidence</th><th>Latency</th><th>Received</th></tr></thead>
                <tbody>
                  {filtered.map((document) => (
                    <tr key={document.id} className={selectedId === document.id ? "selected-row" : ""} onClick={() => setSelectedId(document.id)}>
                      <td><span className="document-cell"><Icon name="documents" />{document.filename}</span></td>
                      <td>{humanize(document.document_type)}</td>
                      <td><StatusMark status={document.status} /></td>
                      <td className="mono">{document.confidence ? formatPercent(document.confidence) : "—"}</td>
                      <td className="mono">{document.total_latency_ms ? `${formatNumber(document.total_latency_ms)} ms` : "—"}</td>
                      <td>{formatDate(document.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState title="No documents match" message="Adjust the search or filters, or upload a new document." />}
          <footer className="table-footer">Showing {filtered.length} of {documents.length} documents</footer>
        </div>
        <aside className="document-detail-pane">
          {detailLoading ? <LoadingState label="Loading document evidence" /> : null}
          {!detailLoading && detail ? (
            <>
              <header className="detail-header">
                <div><h2>{detail.filename}</h2><span>{humanize(detail.document_type)}</span></div>
                <StatusMark status={detail.status} />
              </header>
              {detail.review_reason ? <div className="review-reason"><Icon name="warning" /><span><strong>Review reason</strong>{detail.review_reason}</span></div> : null}
              <div className="classification-line"><strong>{formatPercent(detail.classification.confidence)} classification confidence</strong><span>{detail.classification.reason}</span></div>
              <div className="detail-tabs" role="tablist">
                {(["original", "text", "structured", "validation"] as DetailTab[]).map((value) => (
                  <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? "active-tab" : ""} onClick={() => setTab(value)}>{humanize(value === "text" ? "extracted_text" : value === "structured" ? "structured_data" : value)}</button>
                ))}
              </div>
              <div className="detail-scroll">
                {tab === "original" ? <OriginalPreview document={detail} /> : null}
                {tab === "text" ? <ExtractedText document={detail} /> : null}
                {tab === "structured" ? <StructuredData data={detail.structured_data} /> : null}
                {tab === "validation" ? (
                  <>
                    <section className="detail-section"><h3>Processing trace</h3><PipelineTrace stages={detail.stages} /></section>
                    <section className="detail-section"><h3>Validation rules</h3><ValidationList rules={detail.validation} /></section>
                    <ConfidenceBreakdown confidence={detail.confidence} components={detail.confidence_breakdown.components} definition={detail.confidence_breakdown.definition} />
                  </>
                ) : null}
              </div>
              <footer className="detail-actions">
                <Button busy={busyAction === "retry"} onClick={() => void rerun("retry")}><Icon name="refresh" />Re-run extraction</Button>
                <Button busy={busyAction === "ocr"} onClick={() => void rerun("ocr")}>Re-run OCR</Button>
                {detail.status === "needs_review" ? <Button variant="primary" onClick={onOpenReview}>Open review <Icon name="arrow" /></Button> : null}
              </footer>
            </>
          ) : null}
          {!detailLoading && !detail ? <EmptyState title="Select a document" message="Choose a row to inspect its evidence and pipeline trace." /> : null}
        </aside>
      </section>
      {uploadOpen ? (
        <div className="modal-layer" role="dialog" aria-modal="true" aria-label="Upload document">
          <button className="modal-scrim" aria-label="Close upload" onClick={() => setUploadOpen(false)} />
          <section className="upload-dialog">
            <header><h2>Upload document</h2><button className="icon-button" aria-label="Close" onClick={() => setUploadOpen(false)}><Icon name="close" /></button></header>
            <button className="drop-zone" onClick={() => fileInput.current?.click()}>
              <Icon name="upload" size={28} />
              <strong>Choose a document to process</strong>
              <span>PDF, PNG, JPG or JPEG · maximum 10 MB</span>
            </button>
            <input ref={fileInput} hidden type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
            {uploadProgress !== null ? <div className="upload-progress"><span style={{ width: `${uploadProgress}%` }} /><strong>{uploadProgress}% uploaded · processing stages will follow</strong></div> : null}
            {uploadError ? <div className="inline-error"><Icon name="error" />{uploadError}</div> : null}
          </section>
        </div>
      ) : null}
    </div>
  )
}

function DocumentMetricStrip({ documents }: { documents: DocumentSummary[] }) {
  const total = documents.length
  const accepted = documents.filter((item) => ["accepted", "approved"].includes(item.status)).length
  const review = documents.filter((item) => item.status === "needs_review").length
  const failed = documents.filter((item) => item.status === "failed").length
  const values = [
    ["Processed", total, "documents"],
    ["Auto-accepted", total ? accepted / total * 100 : 0, "%"],
    ["Needs review", total ? review / total * 100 : 0, "%"],
    ["Failed", total ? failed / total * 100 : 0, "%"],
  ] as const
  return (
    <div className="metric-strip compact-metrics">
      {values.map(([label, value, unit]) => <div className="metric-cell" key={label}><span>{label}</span><strong className="mono">{formatNumber(value)}{unit === "%" ? "%" : ""}</strong><small>{unit === "%" ? "of documents" : unit}</small></div>)}
    </div>
  )
}

function OriginalPreview({ document }: { document: DocumentDetail }) {
  const url = api.fileUrl(document.id)
  return (
    <section className="original-preview">
      <div className="preview-toolbar"><span>Inline preview · {document.mime_type}</span><a href={url} target="_blank" rel="noreferrer">Open full size</a></div>
      <DocumentPreview documentId={document.id} filename={document.filename} mimeType={document.mime_type} />
    </section>
  )
}

function ExtractedText({ document }: { document: DocumentDetail }) {
  return (
    <section className="extracted-pages">
      {document.pages.map((page) => (
        <article key={page.page_number}>
          <header><strong>Page {page.page_number}</strong><span>{page.extraction_method} · {page.character_count} characters · {formatNumber(page.latency_ms)} ms{page.ocr_quality !== null ? ` · ${formatPercent(page.ocr_quality)} OCR quality` : ""}</span></header>
          <pre>{page.text || "No readable text on this page."}</pre>
        </article>
      ))}
    </section>
  )
}

function StructuredData({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return <EmptyState title="No structured data" message="Unknown or failed documents are never forced into a schema." />
  return (
    <section className="structured-data">
      <dl>
        {Object.entries(data).filter(([, value]) => !Array.isArray(value)).map(([key, value]) => (
          <div key={key}><dt>{humanize(key)}</dt><dd className={value === null || value === "" ? "missing-value" : ""}>{value === null || value === "" ? "Missing" : String(value)}</dd></div>
        ))}
      </dl>
      {Object.entries(data).filter(([, value]) => Array.isArray(value)).map(([key, value]) => (
        <div className="array-data" key={key}><h3>{humanize(key)}</h3><pre>{JSON.stringify(value, null, 2)}</pre></div>
      ))}
      <details><summary>Raw JSON</summary><pre>{JSON.stringify(data, null, 2)}</pre></details>
    </section>
  )
}
