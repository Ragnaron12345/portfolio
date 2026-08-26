import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { client } from "../api/client";
import { Button, EmptyState, ErrorBanner, LoadingRows, PageHeader, StatusMark, formatNumber } from "../components/Ui";
import { Icon } from "../components/Icon";
import { MarkdownContent } from "../components/MarkdownContent";
import type { DocumentType, KnowledgeDocument, KnowledgeDocumentDetail } from "../types";

const ACCEPTED_EXTENSIONS = new Set(["txt", "md", "pdf", "png", "jpg", "jpeg"]);
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const DOCUMENT_PREVIEW_STEP = 200_000;
const CHUNK_PREVIEW_STEP = 50;
const DOCUMENT_LIST_STEP = 100;

type ReaderView = "document" | "chunks";

export function KnowledgeBasePage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const reader = useRef<HTMLDivElement>(null);
  const readerClose = useRef<HTMLButtonElement>(null);
  const readerTrigger = useRef<HTMLElement | null>(null);
  const listRequest = useRef(0);
  const detailGeneration = useRef(0);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [nextDocumentOffset, setNextDocumentOffset] = useState(0);
  const [hasMoreDocuments, setHasMoreDocuments] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [readerOpen, setReaderOpen] = useState(false);
  const [readerView, setReaderView] = useState<ReaderView>("document");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailPageLoading, setDetailPageLoading] = useState<ReaderView | null>(null);
  const [detailPageError, setDetailPageError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [showUpload, setShowUpload] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("Operations Manual");
  const [documentType, setDocumentType] = useState<DocumentType>("auto");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPage = useCallback(async (offset: number, append: boolean) => {
    const requestId = ++listRequest.current;
    if (append) setLoadingMore(true); else setLoading(true);
    setError(null);
    try {
      const data = await client.getDocuments({
        limit: DOCUMENT_LIST_STEP,
        offset,
        search: query.trim() || undefined,
        source: sourceFilter === "all" ? undefined : sourceFilter,
      });
      if (requestId !== listRequest.current) return;
      setDocuments((current) => {
        return append ? [...current, ...data.filter((item) => !current.some((existing) => existing.id === item.id))] : data;
      });
      setSelectedId((selected) => append ? selected ?? data[0]?.id ?? null : selected && data.some((item) => item.id === selected) ? selected : data[0]?.id ?? null);
      setKnownSources((current) => Array.from(new Set([...current, ...data.map((document) => document.source).filter(Boolean)])).sort());
      setNextDocumentOffset(offset + data.length);
      setHasMoreDocuments(data.length === DOCUMENT_LIST_STEP);
    } catch (reason) {
      if (requestId === listRequest.current) setError(reason instanceof Error ? reason.message : "Unable to load the knowledge base.");
    } finally {
      if (requestId === listRequest.current) {
        if (append) setLoadingMore(false); else setLoading(false);
      }
    }
  }, [query, sourceFilter]);

  const load = useCallback(() => loadPage(0, false), [loadPage]);

  useEffect(() => {
    listRequest.current += 1;
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const generation = ++detailGeneration.current;
    setDetailPageLoading(null);
    setDetailPageError(null);
    if (!selectedId) {
      setSelectedDetail(null);
      return;
    }
    // Full text and chunk payloads can be large. Fetch them only when the
    // operator explicitly opens the reader, not while browsing table rows.
    if (!readerOpen) return;
    let active = true;
    setDetailLoading(true);
    setDetailError(null);
    setDetailPageError(null);
    void client.getDocument(selectedId, { content_limit: DOCUMENT_PREVIEW_STEP, chunk_limit: CHUNK_PREVIEW_STEP })
      .then((detail) => {
        if (active && generation === detailGeneration.current) setSelectedDetail(detail);
      })
      .catch((reason: unknown) => {
        if (active && generation === detailGeneration.current) {
          setSelectedDetail(null);
          setDetailError(reason instanceof Error ? reason.message : "Unable to load document content.");
        }
      })
      .finally(() => {
        if (active && generation === detailGeneration.current) setDetailLoading(false);
      });
    return () => { active = false; };
  }, [readerOpen, selectedId]);

  useEffect(() => {
    if (!readerOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    readerClose.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [readerOpen]);

  const selectedSummary = documents.find((document) => document.id === selectedId) ?? null;
  const selected = selectedDetail?.id === selectedId ? selectedDetail : selectedSummary;
  const sources = knownSources;
  const visible = useMemo(() => documents.filter((document) => {
    const searchText = `${document.title} ${document.filename}`.toLowerCase();
    return searchText.includes(query.trim().toLowerCase()) && (sourceFilter === "all" || document.source === sourceFilter);
  }), [documents, query, sourceFilter]);
  const chunks = documents.reduce((sum, document) => sum + (document.chunk_count ?? 0), 0);
  const indexed = documents.filter((document) => document.status === "indexed").length;

  function chooseFile(candidate: File | null) {
    if (!candidate) return;
    const extension = candidate.name.split(".").at(-1)?.toLowerCase() ?? "";
    if (!ACCEPTED_EXTENSIONS.has(extension)) {
      setError("Only .txt, .md, .pdf, .png, .jpg and .jpeg documents are accepted.");
      return;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setError("The maximum upload size is 100 MB.");
      return;
    }
    setFile(candidate);
    setTitle((current) => current || candidate.name.replace(/\.[^.]+$/, "").replaceAll(/[-_]+/g, " "));
    setError(null);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !title.trim() || !source.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await client.uploadDocument(file, title.trim(), source.trim(), documentType);
      setShowUpload(false);
      setFile(null);
      setTitle("");
      setDocumentType("auto");
      await load();
      setSelectedId(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The document could not be uploaded.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(document: KnowledgeDocument) {
    if (!window.confirm(`Delete “${document.title}” and all indexed chunks?`)) return;
    setSaving(true);
    setError(null);
    try {
      await client.deleteDocument(document.id);
      setReaderOpen(false);
      setSelectedDetail(null);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The document could not be deleted.");
    } finally {
      setSaving(false);
    }
  }

  function openDocument(id: string, trigger?: HTMLElement) {
    readerTrigger.current = trigger ?? document.activeElement as HTMLElement | null;
    setSelectedId(id);
    setReaderView("document");
    setReaderOpen(true);
  }

  async function loadNextContentPage() {
    if (!selectedDetail || selectedDetail.next_content_offset === null || selectedDetail.next_content_offset === undefined || detailPageLoading) return;
    const generation = detailGeneration.current;
    const documentId = selectedDetail.id;
    const expectedOffset = selectedDetail.next_content_offset;
    setDetailPageLoading("document");
    setDetailPageError(null);
    try {
      const page = await client.getDocument(documentId, {
        content_offset: expectedOffset,
        content_limit: DOCUMENT_PREVIEW_STEP,
        chunk_limit: 0,
      });
      if (generation !== detailGeneration.current) return;
      setSelectedDetail((current) => current?.id === page.id && current.next_content_offset === expectedOffset ? {
        ...current,
        content: `${current.content ?? ""}${page.content ?? ""}`,
        content_limit: page.content_limit,
        content_total: page.content_total,
        content_complete: page.content_complete,
        next_content_offset: page.next_content_offset,
      } : current);
    } catch (reason) {
      if (generation === detailGeneration.current) setDetailPageError(reason instanceof Error ? reason.message : "Unable to load the next document section.");
    } finally {
      if (generation === detailGeneration.current) setDetailPageLoading(null);
    }
  }

  async function loadNextChunkPage() {
    if (!selectedDetail || selectedDetail.next_chunk_offset === null || selectedDetail.next_chunk_offset === undefined || detailPageLoading) return;
    const generation = detailGeneration.current;
    const documentId = selectedDetail.id;
    const expectedOffset = selectedDetail.next_chunk_offset;
    setDetailPageLoading("chunks");
    setDetailPageError(null);
    try {
      const page = await client.getDocument(documentId, {
        content_limit: 0,
        chunk_offset: expectedOffset,
        chunk_limit: CHUNK_PREVIEW_STEP,
      });
      if (generation !== detailGeneration.current) return;
      setSelectedDetail((current) => current?.id === page.id && current.next_chunk_offset === expectedOffset ? {
        ...current,
        chunks: [...current.chunks, ...page.chunks],
        chunk_limit: page.chunk_limit,
        chunk_total: page.chunk_total,
        chunks_complete: page.chunks_complete,
        next_chunk_offset: page.next_chunk_offset,
      } : current);
    } catch (reason) {
      if (generation === detailGeneration.current) setDetailPageError(reason instanceof Error ? reason.message : "Unable to load the next chunk page.");
    } finally {
      if (generation === detailGeneration.current) setDetailPageLoading(null);
    }
  }

  function closeReader() {
    detailGeneration.current += 1;
    setDetailPageLoading(null);
    setDetailPageError(null);
    setReaderOpen(false);
    requestAnimationFrame(() => readerTrigger.current?.focus());
  }

  function handleReaderKeys(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeReader();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(reader.current?.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])") ?? []);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <main className="page page--knowledge">
      <PageHeader title="Knowledge Base" actions={<Button variant="primary" icon="upload" onClick={() => setShowUpload((value) => !value)}>Upload document</Button>} />
      {error ? <ErrorBanner message={error} retry={() => void load()} /> : null}
      <div className="knowledge-layout">
        <div className="knowledge-main">
          <section className="ingestion-metrics" aria-label="Ingestion summary">
            <div><Icon name="document" /><span>Loaded documents</span><strong>{formatNumber(documents.length)}{hasMoreDocuments ? "+" : ""}</strong></div>
            <div><Icon name="knowledge" /><span>Chunks</span><strong>{formatNumber(chunks)}</strong></div>
            <div><Icon name="check" /><span>Indexed</span><strong>{indexed}</strong></div>
            <div><Icon name="warning" /><span>Rejected uploads</span><strong>Not stored</strong></div>
          </section>
          <section className="kb-method-note" aria-labelledby="kb-method-title">
            <div>
              <span className="kb-method-note__index">01—04</span>
              <div><strong id="kb-method-title">How indexing works</strong><p>Parse → split with overlap → embed each chunk → store its vector and source metadata for retrieval. Ingestion is atomic: only completed documents appear here; rejected uploads return an exact error and are not recorded as fake failed documents.</p></div>
            </div>
            <details>
              <summary>Chunking details</summary>
              <p>Text is normalized and split at a nearby paragraph, sentence, or word boundary. The current profile uses chunks up to 900 characters with 140-character overlap, preserving page numbers for PDFs. During retrieval, the improved pipeline combines semantic similarity with keyword overlap and returns the strongest evidence.</p>
            </details>
          </section>
          <div className="knowledge-toolbar">
            <label className="search-field"><Icon name="search" /><span className="sr-only">Search by document title or filename</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or filename…" /></label>
            <label className="field"><span>Source metadata</span><select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">All sources</option>{sources.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
            <Button icon="refresh" onClick={() => void load()} disabled={loading}>Refresh</Button>
          </div>
          {loading ? <LoadingRows rows={7} /> : visible.length ? (
            <div className="table-scroll">
              <table className="data-table knowledge-table">
                <thead><tr><th>Title / filename</th><th>Source metadata</th><th>Type</th><th>Chunks</th><th>Embedding status</th><th>Updated</th></tr></thead>
                <tbody>{visible.map((documentItem) => (
                  <tr
                    key={documentItem.id}
                    className={documentItem.id === selectedId ? "selected-row" : ""}
                    onClick={(event) => openDocument(documentItem.id, event.currentTarget)}
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openDocument(documentItem.id, event.currentTarget);
                      }
                    }}
                  >
                    <td><button className="document-title" onClick={(event) => { event.stopPropagation(); openDocument(documentItem.id, event.currentTarget); }}><Icon name="document" />{documentItem.title}</button><small>{documentItem.filename}</small></td>
                    <td>{documentItem.source}</td><td>{documentItem.mime_type.split("/").at(-1)?.toUpperCase()}</td><td>{formatNumber(documentItem.chunk_count ?? 0)}</td>
                    <td><StatusMark tone={documentItem.status === "empty" ? "warning" : "success"}>{documentItem.status ?? "indexed"}</StatusMark></td>
                    <td>{new Date(documentItem.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <EmptyState title="No documents found" message="Adjust title, filename, or source filters—or upload a policy document." action={<Button variant="primary" icon="upload" onClick={() => setShowUpload(true)}>Upload document</Button>} />}
          {hasMoreDocuments ? <div className="kb-list-pagination"><Button onClick={() => void loadPage(nextDocumentOffset, true)} disabled={loadingMore}>{loadingMore ? "Loading more…" : `Load next ${DOCUMENT_LIST_STEP} documents`}</Button><span>{formatNumber(documents.length)} matching documents loaded; search and source filters run on the server.</span></div> : documents.length ? <p className="kb-list-complete">All {formatNumber(documents.length)} matching documents are loaded.</p> : null}
          {showUpload ? (
            <form className="upload-panel" onSubmit={(event) => void upload(event)}>
              <div className="section-heading"><h2>Upload document</h2><button type="button" className="icon-button" aria-label="Close upload form" onClick={() => setShowUpload(false)}><Icon name="close" /></button></div>
              <button
                type="button"
                className="drop-zone"
                onClick={() => fileInput.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => { event.preventDefault(); chooseFile(event.dataTransfer.files[0] ?? null); }}
              >
                <Icon name="upload" /><strong>{file ? file.name : "Drag and drop your file here, or browse"}</strong><span>.txt, .md, .pdf, .png, .jpg, .jpeg · maximum transport size 100 MB</span>
              </button>
              <input ref={fileInput} type="file" hidden accept=".txt,.md,.pdf,.png,.jpg,.jpeg,text/plain,text/markdown,application/pdf,image/png,image/jpeg" onChange={(event) => chooseFile(event.target.files?.[0] ?? null)} />
              <p className="section-caption">Parser safety limits are independent of file bytes: at most 20 million decoded characters, 500 PDF pages, and 25,000 indexed chunks. Files exceeding a parsed-content limit are rejected with the exact reason.</p>
              <div className="upload-fields"><label className="field"><span>Title</span><input value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={200} /></label><label className="field"><span>Source metadata</span><input value={source} onChange={(event) => setSource(event.target.value)} required maxLength={200} /><small>Origin or owner, for example Risk &amp; Compliance—not the document title.</small></label><label className="field field--routing"><span>Document type</span><select aria-label="Document type" value={documentType} onChange={(event) => setDocumentType(event.target.value as DocumentType)}><option value="auto">Auto-detect</option><option value="general">General knowledge</option><option value="invoice">Invoice</option></select><small>Auto routes invoice-shaped documents to extraction; general documents go directly to RAG indexing.</small></label></div>
              <div className="form-actions"><Button type="button" onClick={() => setShowUpload(false)}>Cancel</Button><Button variant="primary" icon="upload" type="submit" disabled={!file || !title.trim() || !source.trim() || saving}>{saving ? "Indexing…" : "Upload & index"}</Button></div>
            </form>
          ) : null}
        </div>
        <aside className="knowledge-detail" aria-label="Document detail">
          {selected ? (
            <>
              <header><h2>{selected.title}</h2><StatusMark tone={selected.status === "empty" ? "warning" : "success"}>{selected.status ?? "indexed"}</StatusMark></header>
              <dl className="definition-list definition-list--stacked">
                <div><dt>Source</dt><dd>{selected.source}</dd></div><div><dt>File name</dt><dd>{selected.filename}</dd></div><div><dt>Type</dt><dd>{selected.mime_type}</dd></div><div><dt>Chunks</dt><dd>{selected.chunk_count ?? 0}</dd></div><div><dt>Uploaded</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div>
              </dl>
              <Button className="kb-open-reader" variant="primary" icon="document" onClick={(event) => openDocument(selected.id, event.currentTarget)}>Open document</Button>
              <section className="ingestion-timeline"><h3>Persisted ingestion status</h3><ol>{["Parsed", "Chunked", "Embedded", "Indexed"].map((stage) => <li key={stage}><span className="trace-node" /><strong>{stage}</strong><small>{selected.status === "empty" ? "No indexable content" : "Complete"}</small></li>)}</ol><p className="section-caption">A document row is created only after the atomic parse, chunk, embedding and index transaction succeeds.</p></section>
              <section><h3>Metadata</h3><pre className="metadata-preview">{JSON.stringify(selected.metadata ?? {}, null, 2)}</pre></section>
              <footer><span className="knowledge-detail__retention">Extracted content is read-only after indexing. Upload a new version to replace it.</span><Button variant="danger" icon="trash" onClick={() => void remove(selected)} disabled={saving}>Delete</Button></footer>
            </>
          ) : <EmptyState title="No document selected" message="Choose a document to inspect its source and indexed evidence." />}
        </aside>
      </div>
      {readerOpen ? (
        <div className="kb-reader-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeReader(); }}>
          <div ref={reader} className="kb-reader" role="dialog" aria-modal="true" aria-labelledby="kb-reader-title" onKeyDown={handleReaderKeys}>
            <header className="kb-reader__header">
              <div><span>Indexed evidence</span><h2 id="kb-reader-title">{selected?.title ?? "Document"}</h2><p>{selected?.source} · {selected?.filename}</p></div>
              <button ref={readerClose} type="button" className="icon-button" aria-label="Close document reader" onClick={closeReader}><Icon name="close" /></button>
            </header>
            <div className="kb-reader__toolbar" role="group" aria-label="Document reader view">
              <button type="button" aria-pressed={readerView === "document"} onClick={() => setReaderView("document")}>Full document</button>
              <button type="button" aria-pressed={readerView === "chunks"} onClick={() => setReaderView("chunks")}>Indexed chunks <span>{selectedDetail?.chunk_total ?? selected?.chunk_count ?? 0}</span></button>
              <small>Read-only normalized text</small>
            </div>
            <div className="kb-reader__body">
              {detailLoading ? <LoadingRows rows={8} /> : detailError ? <ErrorBanner message={detailError} retry={() => { const current = selectedId; setSelectedId(null); requestAnimationFrame(() => setSelectedId(current)); }} /> : readerView === "document" ? (
                <article className="kb-document-view">
                  <div className="kb-reader-progress"><span>Displaying {formatNumber(selectedDetail?.content?.length ?? 0)} of {formatNumber(selectedDetail?.content_total ?? selectedDetail?.content?.length ?? 0)} normalized characters</span><strong>{selectedDetail?.content_complete ? "Complete document" : "Progressive network preview"}</strong></div>
                  <MarkdownContent text={selectedDetail?.content || "No extracted content is available for this document."} />
                  {detailPageError ? <p className="document-inline-error">{detailPageError}</p> : null}
                  {!selectedDetail?.content_complete && typeof selectedDetail?.next_content_offset === "number" ? <Button className="kb-reader-more" onClick={() => void loadNextContentPage()} disabled={detailPageLoading !== null}>{detailPageLoading === "document" ? "Loading next section…" : `Show next ${formatNumber(Math.min(DOCUMENT_PREVIEW_STEP, Math.max(0, (selectedDetail?.content_total ?? 0) - (selectedDetail?.content?.length ?? 0))))} characters`}</Button> : null}
                </article>
              ) : selectedDetail?.chunks.length ? (
                <div className="kb-chunks-view"><div className="kb-reader-progress"><span>Displaying {selectedDetail.chunks.length} of {selectedDetail.chunk_total ?? selectedDetail.chunks.length} indexed chunks</span><strong>{selectedDetail.chunks_complete ? "Complete index" : "Progressive network preview"}</strong></div><ol className="kb-chunk-list">{selectedDetail.chunks.map((chunk) => <li key={chunk.id}><header><span>Chunk {String(chunk.chunk_index + 1).padStart(2, "0")}</span><small>{chunk.page_number ? `Page ${chunk.page_number}` : "Continuous text"}</small></header><MarkdownContent text={chunk.content} /></li>)}</ol>{detailPageError ? <p className="document-inline-error">{detailPageError}</p> : null}{!selectedDetail.chunks_complete && typeof selectedDetail.next_chunk_offset === "number" ? <Button className="kb-reader-more" onClick={() => void loadNextChunkPage()} disabled={detailPageLoading !== null}>{detailPageLoading === "chunks" ? "Loading next chunks…" : `Show next ${Math.min(CHUNK_PREVIEW_STEP, Math.max(0, (selectedDetail.chunk_total ?? 0) - selectedDetail.chunks.length))} chunks`}</Button> : null}</div>
              ) : <EmptyState title="No chunks available" message="This document did not return any indexed chunk records." />}
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
