import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { client } from "../api/client";
import type { Citation, KnowledgeDocumentDetail } from "../types";
import { Icon } from "./Icon";
import { MarkdownContent } from "./MarkdownContent";
import { formatPercent } from "./Ui";

const PREVIEW_LIMIT = 200_000;

function relevanceLabel(score?: number) {
  if (score === undefined) return "Not reported";
  if (score >= 0.8) return "Strong match";
  if (score >= 0.6) return "Relevant match";
  return "Supporting match";
}

function documentText(document: KnowledgeDocumentDetail | null) {
  if (!document) return "";
  if (document.content) return document.content;
  return document.chunks.map((chunk) => chunk.content.trim()).filter(Boolean).join("\n\n");
}

export function SourceDocumentDialog({ citation, onClose }: { citation: Citation | null; onClose: () => void }) {
  const [detail, setDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingNext, setLoadingNext] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const requestGeneration = useRef(0);

  useEffect(() => {
    if (!citation) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => previouslyFocused?.focus();
  }, [citation]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    setLoadingNext(false);
    let cancelled = false;
    setDetail(null);
    setError(null);
    if (!citation?.document_id) return;
    setLoading(true);
    void client.getDocument(citation.document_id, {
      content_limit: PREVIEW_LIMIT,
      chunk_offset: citation.chunk_index ?? 0,
      chunk_limit: 1,
    })
      .then((value) => { if (!cancelled && generation === requestGeneration.current) setDetail(value); })
      .catch((reason: unknown) => {
        if (!cancelled && generation === requestGeneration.current) setError(reason instanceof Error ? reason.message : "Full document preview is unavailable.");
      })
      .finally(() => { if (!cancelled && generation === requestGeneration.current) setLoading(false); });
    return () => { cancelled = true; };
  }, [citation]);

  const fullText = useMemo(() => documentText(detail), [detail]);
  const matchedChunk = useMemo(() => detail?.chunks.find((chunk) => (
    citation?.chunk_id ? chunk.id === citation.chunk_id : chunk.chunk_index === citation?.chunk_index
  )), [citation, detail]);

  if (!citation) return null;

  async function loadNextContentPage() {
    if (!detail || typeof detail.next_content_offset !== "number" || loadingNext) return;
    const generation = requestGeneration.current;
    const documentId = detail.id;
    const expectedOffset = detail.next_content_offset;
    setLoadingNext(true);
    setError(null);
    try {
      const page = await client.getDocument(documentId, {
        content_offset: expectedOffset,
        content_limit: PREVIEW_LIMIT,
        chunk_limit: 0,
      });
      if (generation !== requestGeneration.current) return;
      setDetail((current) => current?.id === page.id && current.next_content_offset === expectedOffset ? {
        ...current,
        content: `${current.content ?? ""}${page.content ?? ""}`,
        content_limit: page.content_limit,
        content_total: page.content_total,
        content_complete: page.content_complete,
        next_content_offset: page.next_content_offset,
      } : current);
    } catch (reason) {
      if (generation === requestGeneration.current) setError(reason instanceof Error ? reason.message : "The next document section could not be loaded.");
    } finally {
      if (generation === requestGeneration.current) setLoadingNext(false);
    }
  }

  function closeDialog() {
    requestGeneration.current += 1;
    setLoadingNext(false);
    onClose();
  }

  function trapFocus(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? [])
      .filter((element) => !element.hasAttribute("disabled"));
    if (!focusable.length) return;
    const first = focusable[0]!;
    const last = focusable.at(-1)!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) closeDialog();
  }

  const score = citation.score;
  const excerpt = matchedChunk?.content || citation.excerpt || "No excerpt was persisted for this citation.";
  const visibleText = fullText;

  return (
    <div className="document-dialog-backdrop" onMouseDown={closeFromBackdrop}>
      <section
        className="document-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-dialog-title"
        ref={dialogRef}
        tabIndex={-1}
        onKeyDown={trapFocus}
      >
        <header>
          <div>
            <span className="eyebrow">Retrieved evidence</span>
            <h2 id="source-dialog-title">{detail?.title ?? citation.title}</h2>
            <p>{detail?.source ?? citation.source}{citation.page_number ? ` · page ${citation.page_number}` : ""}</p>
          </div>
          <button className="icon-button" type="button" aria-label="Close document preview" onClick={closeDialog} autoFocus><Icon name="close" /></button>
        </header>
        <div className="document-dialog__body">
          <section className="relevance-card" aria-label="Retrieval relevance">
            <div><span>Relevance</span><strong>{score === undefined ? "—" : formatPercent(score)}</strong><small>{relevanceLabel(score)}</small></div>
            <span className="relevance-meter" aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(1, score ?? 0)) * 100}%` }} /></span>
            <p>This similarity score ranks the retrieved chunk against the request. It is not a probability that the answer is correct.</p>
          </section>
          <section>
            <div className="document-section-heading"><h3>Matched chunk</h3><code>#{citation.chunk_index ?? matchedChunk?.chunk_index ?? "—"}</code></div>
            <MarkdownContent className="document-excerpt" text={excerpt} />
          </section>
          <section>
            <div className="document-section-heading"><h3>Full document</h3>{detail ? <code>{detail.chunk_count ?? detail.chunks.length} chunks</code> : null}</div>
            {loading ? <div className="document-loading" role="status">Loading document content…</div> : null}
            {error ? <p className="document-inline-error">{error} The persisted citation excerpt remains available above.</p> : null}
            {!loading && visibleText ? <MarkdownContent className="document-content" text={visibleText} /> : null}
            {!loading && !visibleText && !error ? <p className="document-empty">No full-text preview is available.</p> : null}
            {!detail?.content_complete && typeof detail?.next_content_offset === "number" ? <div className="document-preview-note"><p>Loaded {fullText.length.toLocaleString()} of {(detail.content_total ?? fullText.length).toLocaleString()} characters from the server.</p><button type="button" className="text-action" disabled={loadingNext} onClick={() => void loadNextContentPage()}>{loadingNext ? "Loading…" : `Show next ${Math.min(PREVIEW_LIMIT, Math.max(0, (detail.content_total ?? 0) - fullText.length)).toLocaleString()} characters`}</button></div> : null}
          </section>
        </div>
      </section>
    </div>
  );
}
