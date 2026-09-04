import { useEffect, useState } from "react";
import { client } from "../api/client";
import { Icon } from "../components/Icon";
import { Timeline } from "../components/Timeline";
import {
  Button,
  EmptyState,
  ErrorBanner,
  LoadingRows,
  PageHeader,
  ReadableData,
  RefreshMeta,
  RiskTag,
  StatusMark,
  formatPercent,
  formatTime,
  humanize,
} from "../components/Ui";
import { usePollingResource } from "../hooks/usePollingResource";
import { queryParam, setQueryParam, setQueryParams } from "../router";
import type { Approval, Execution } from "../types";

function ReviewListItem({ review, selected, onSelect }: { review: Approval; selected: boolean; onSelect: () => void }) {
  const risk = review.execution?.classification?.risk_level ?? String(review.decision_context.risk_level ?? review.decision_context.risk ?? "medium");
  return (
    <button className={`review-list-item${selected ? " review-list-item--selected" : ""}`} onClick={onSelect} aria-pressed={selected}>
      <span className={`review-list-item__icon review-list-item__icon--${risk.toLowerCase()}`}><Icon name={risk.toLowerCase() === "high" ? "error" : risk.toLowerCase() === "medium" ? "warning" : "shield"} /></span>
      <span className="review-list-item__copy">
        <strong>{review.title}</strong>
        <span>{review.reason}</span>
        <small><RiskTag risk={risk} /> {formatTime(review.status === "pending" ? review.created_at : review.resolved_at ?? review.created_at)}</small>
      </span>
    </button>
  );
}

function ReviewEvidence({ execution, approval }: { execution?: Execution; approval: Approval }) {
  const classification = execution?.classification;
  return (
    <div className="review-evidence">
      <header className="review-evidence__header">
        <div><span className="eyeline">{execution?.workflow ?? approval.workflow}</span><h2>{approval.title}</h2><span className="mandatory-tag">{classification?.risk_level === "high" ? "Mandatory review" : "Human review"}</span></div>
        <StatusMark status={approval.status} />
      </header>
      <dl className="review-meta">
        <div><dt>Execution ID</dt><dd>{approval.execution_id}</dd></div>
        {classification ? <><div><dt>Category</dt><dd className="mono">{classification.category}</dd></div><div><dt>Risk</dt><dd><RiskTag risk={classification.risk_level} /></dd></div><div><dt>Confidence</dt><dd>{formatPercent(classification.confidence <= 1 ? classification.confidence * 100 : classification.confidence, 0)}</dd></div></> : null}
      </dl>
      <section className="review-field"><h3>Original request</h3><div className="review-field__surface"><ReadableData value={execution?.input ?? approval.decision_context} /></div></section>
      <section className="review-field"><h3>AI decision</h3><div className="review-field__surface"><p>{execution?.decision_summary ?? "Decision requires operator review."}</p></div></section>
      <section className="review-field"><h3>Review reason</h3><div className="review-field__surface"><p>{approval.reason}</p></div></section>
      {classification ? <section className="review-field"><h3>Classification reason</h3><div className="review-field__surface"><p>{classification.reason}</p></div></section> : null}
      {execution?.generated_draft ? <section className="review-field"><h3>Grounded response</h3><div className="review-field__surface"><p>{execution.generated_draft}</p></div></section> : null}
      {execution?.sources.length ? <section className="review-field"><h3>Policy sources</h3><div className="review-source-list">{execution.sources.map((source) => <article key={source.id}><Icon name="file" /><span><strong>{source.title}</strong>{source.excerpt ? <small>{source.excerpt}</small> : null}</span><b>{formatPercent(source.relevance <= 1 ? source.relevance * 100 : source.relevance, 0)}</b></article>)}</div></section> : null}
      {execution?.validations.length ? <section className="review-field"><h3>Validation evidence</h3><div className="review-validation-list">{execution.validations.map((validation) => <article key={validation.rule} className={validation.passed ? "is-passed" : "is-failed"}><Icon name={validation.passed ? "check" : "error"} /><span><strong>{humanize(validation.rule)}</strong><small>{validation.message}</small></span></article>)}</div></section> : null}
    </div>
  );
}

function ReviewRail({ approval, execution }: { approval: Approval; execution?: Execution }) {
  return (
    <aside className="review-rail">
      <section><h2>Execution timeline</h2><Timeline events={execution?.events ?? []} /></section>
      <section><h2>Execution details</h2><dl className="rail-details"><div><dt>AI attempts</dt><dd>{execution?.ai_attempt_count ?? "Not recorded"}</dd></div><div><dt>Max attempts / provider</dt><dd>2</dd></div><div><dt>Failed AI attempts</dt><dd>{execution?.retry_count ?? 0}</dd></div><div><dt>Retry policy</dt><dd>Exponential backoff</dd></div><div><dt>Current stage</dt><dd>{humanize(execution?.current_stage ?? "review")}</dd></div></dl></section>
      <section><h2>Decision history</h2>{approval.history.length ? <ol className="decision-history">{approval.history.map((entry) => <li key={`${entry.created_at}-${entry.decision}`}><strong>{humanize(entry.decision)}</strong><span>{entry.reviewer} · {formatTime(entry.created_at, true)}</span>{entry.note ? <p>{entry.note}</p> : null}</li>)}</ol> : <p className="muted-copy">No decisions yet.</p>}</section>
    </aside>
  );
}

export function ReviewQueuePage() {
  const selectedId = queryParam("review");
  const statusFilter = queryParam("status") ?? "pending";
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState<"approved" | "rejected" | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [successMessage, setSuccessMessage] = useState("");

  const list = usePollingResource(async () => ({ ...await client.getApprovals(statusFilter), filter: statusFilter }), [statusFilter], 5_000);
  const visibleList = list.data?.filter === statusFilter ? list.data : null;

  useEffect(() => {
    if (!visibleList) return;
    const selectionIsVisible = selectedId ? visibleList.items.some((review) => review.id === selectedId) : false;
    const nextId = selectionIsVisible ? selectedId : visibleList.items[0]?.id ?? null;
    if (nextId !== selectedId) setQueryParam("review", nextId, true);
  }, [selectedId, visibleList]);

  const detail = usePollingResource(async () => {
    if (!selectedId) throw new Error("Select a review item to inspect its evidence.");
    const approval = await client.getApproval(selectedId);
    const execution = await client.getExecution(approval.execution_id).catch(() => approval.execution);
    if (!execution) throw new Error("The linked execution detail is unavailable.");
    const events = await client.getExecutionEvents(execution.execution_id).catch(() => execution.events);
    const timeline = execution.events.length ? execution.events : events;
    return { approval: { ...approval, execution: { ...execution, events: timeline } }, execution: { ...execution, events: timeline } };
  }, [selectedId], selectedId ? 5_000 : 0);

  const listSelection = visibleList?.items.find((review) => review.id === selectedId);
  const selectedDetail = detail.data?.approval.id === selectedId ? detail.data : null;
  const approval = selectedDetail?.approval ?? listSelection;
  const execution = selectedDetail?.execution ?? listSelection?.execution;

  async function decide(decision: "approved" | "rejected") {
    if (!approval) return;
    setSubmitting(decision);
    setActionError(null);
    setSuccessMessage("");
    try {
      const resolved = await client.decideApproval(approval.id, decision, note.trim());
      if (decision === "rejected") {
        setSuccessMessage("Rejection recorded. No protected side effect will run.");
      } else if (resolved.execution?.status === "failed") {
        setActionError(new Error(`Approval recorded, but the authorized side effect failed: ${resolved.execution.error || "See the execution timeline for the exact failure."}`));
      } else if (resolved.execution?.status === "completed_with_warning") {
        setSuccessMessage("Approval recorded. Deterministic policy kept the protected side effect blocked.");
      } else if (resolved.execution?.status === "completed") {
        setSuccessMessage("Approval recorded. Authorized side effects completed.");
      } else {
        setSuccessMessage("Approval recorded. The execution remains visible in its current state.");
      }
      setNote("");
      list.reload();
      detail.reload();
    } catch (candidate) {
      setActionError(candidate instanceof Error ? candidate : new Error("The review decision could not be recorded."));
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="review-page">
      <PageHeader title="Human review" action={<RefreshMeta lastUpdated={list.lastUpdated} refreshing={list.refreshing || detail.refreshing} onRefresh={() => { list.reload(); detail.reload(); }} />} />
      <div className="review-toolbar">
        <strong>{statusFilter === "pending" ? "Pending · newest first" : "Decision history · newest first"}</strong>
        <div className="segmented-control" role="group" aria-label="Review status filter">
          <button className={statusFilter === "pending" ? "is-active" : ""} onClick={() => setQueryParams({ status: "pending", review: null })}>Pending</button>
          <button className={statusFilter === "resolved" ? "is-active" : ""} onClick={() => setQueryParams({ status: "resolved", review: null })}>Resolved</button>
        </div>
      </div>
      {list.error && !visibleList ? <ErrorBanner error={list.error} onRetry={list.reload} /> : null}
      {actionError ? <ErrorBanner error={actionError} title="Review recorded; authorized action failed" /> : null}
      {successMessage ? <div className="success-banner" role="status"><Icon name="check" />{successMessage}</div> : null}

      <div className="review-layout">
        <section className="review-list" aria-label="Review items">
          {list.loading || (!visibleList && !list.error) ? <LoadingRows count={5} /> : null}
          {visibleList?.items.map((review) => <ReviewListItem key={review.id} review={review} selected={review.id === selectedId} onSelect={() => { setQueryParam("review", review.id); setSuccessMessage(""); setNote(""); }} />)}
          {!list.loading && visibleList?.items.length === 0 ? <EmptyState title={statusFilter === "pending" ? "Review queue is clear" : "No decision history"} body={statusFilter === "pending" ? "High-risk and low-confidence decisions will appear here." : "Resolved reviews will appear here."} icon="reviews" /> : null}
        </section>
        <section className="review-main" aria-label="Selected review evidence">
          {detail.loading && selectedId ? <LoadingRows count={8} /> : null}
          {detail.error && selectedId ? <ErrorBanner error={detail.error} onRetry={detail.reload} /> : null}
          {approval && !detail.loading ? <ReviewEvidence approval={approval} execution={execution} /> : null}
          {!selectedId && !detail.loading ? <EmptyState title="Select a review" body="Choose an item to inspect its complete decision context." icon="reviews" /> : null}
        </section>
        {approval ? <ReviewRail approval={approval} execution={execution} /> : <aside className="review-rail" />}
      </div>

      {approval ? (
        <footer className="review-actions">
          <label><span>Reviewer note</span><textarea value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} placeholder="Add a reviewer note" disabled={approval.status !== "pending" || submitting !== null} /><small>{note.length} / 1000</small></label>
          <Button variant="danger" onClick={() => void decide("rejected")} disabled={approval.status !== "pending" || submitting !== null}><Icon name="error" /> {submitting === "rejected" ? "Rejecting…" : "Reject"}</Button>
          <Button variant="primary" onClick={() => void decide("approved")} disabled={approval.status !== "pending" || submitting !== null}><Icon name="shield" /> {submitting === "approved" ? "Approving…" : "Approve"}</Button>
        </footer>
      ) : null}
    </div>
  );
}
