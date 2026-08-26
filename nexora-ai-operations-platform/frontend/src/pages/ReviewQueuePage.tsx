import { useCallback, useEffect, useMemo, useState } from "react";
import { client } from "../api/client";
import { SourceDocumentDialog } from "../components/SourceDocumentDialog";
import { stripMarkdownEmphasis } from "../components/MarkdownContent";
import { Button, EmptyState, ErrorBanner, LoadingRows, PageHeader, StatusMark } from "../components/Ui";
import type { Citation, ReviewItem, RiskLevel } from "../types";

function riskTone(risk?: RiskLevel | "unknown") {
  return risk === "high" ? "danger" as const : risk === "medium" ? "warning" as const : "neutral" as const;
}

function reviewRisk(item: ReviewItem) {
  return item.risk_level ?? item.request?.risk_level ?? "unknown";
}

function reviewConfidence(item: ReviewItem) {
  return item.confidence ?? item.request?.confidence ?? 0;
}

function reviewResponse(item: ReviewItem) {
  return item.edited_response ?? item.response ?? item.request?.response ?? "";
}

function statusTone(status?: string) {
  if (status?.includes("reject") || status === "failed" || status === "decision_failed") return "danger" as const;
  if (status?.includes("pending") || status?.includes("review")) return "warning" as const;
  if (status?.includes("approv") || status === "completed") return "success" as const;
  return "neutral" as const;
}

function humanize(value?: string | null) {
  if (!value) return "—";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escalationExplanation(reason: string, item: ReviewItem) {
  const normalized = reason.toLowerCase();
  const message = item.message ?? item.request?.message ?? "";
  if (normalized.includes("high-risk")) {
    const cardTheft = /stolen|lost|card/i.test(message);
    return {
      title: cardTheft ? "Card-security action requires oversight" : "High-risk action requires oversight",
      detail: cardTheft
        ? "The request concerns a stolen payment card. Freezing access, identity-safe verification and replacement instructions can affect customer funds, so a reviewer must confirm the exact next steps before release."
        : "The classifier detected an action that can affect customer funds, identity, account access or an irreversible workflow. Safety policy requires a human decision before release.",
    };
  }
  if (normalized.includes("cross-document") || normalized.includes("conflict")) return { title: "Conflicting policy evidence", detail: "Retrieved documents contain materially different instructions for the same decision. The system preserved both sources instead of choosing one without authority." };
  if (normalized.includes("no adequate") || normalized.includes("retrieval evidence")) return { title: "Insufficient knowledge evidence", detail: "No indexed chunk passed the retrieval evidence threshold. A human should verify the answer or add an authoritative document." };
  if (normalized.includes("confidence") && normalized.includes("below")) return { title: "Confidence gate failed", detail: "The combined workflow score fell below the configured release threshold after retrieval, grounding, structure and tool outcomes were evaluated." };
  if (normalized.includes("tool") && normalized.includes("approval")) return { title: "Tool approval required", detail: "An allowlisted tool produced a pending-approval action. A reviewer must verify its arguments and operational impact before execution." };
  if (normalized.includes("unsupported") || normalized.includes("adversarial")) return { title: "Unsupported or adversarial request", detail: "The request is outside the documented support scope or contains instructions that attempt to override the platform’s safety policy." };
  if (normalized.includes("model quality") || normalized.includes("quality tier") || normalized.includes("quality floor")) return { title: "Model quality floor not met", detail: "The provider completed, but the model that produced the available guidance was below the quality tier required for this request. The response is retained as degraded evidence and cannot be released without human review." };
  if (normalized.includes("provider") || normalized.includes("model")) return { title: "Provider execution unavailable", detail: "The configured model route could not complete successfully. A reviewer can use the persisted evidence and provider-attempt audit trail." };
  return { title: humanize(reason), detail: "A configured validation gate was triggered. Review the original request, classification rationale, retrieved evidence and generated response before deciding." };
}

export function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("actionable");
  const [riskFilter, setRiskFilter] = useState("all");
  const [editedResponse, setEditedResponse] = useState("");
  const [notes, setNotes] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const reviews = await client.getReviews(null);
      setItems(reviews);
      setSelectedId((current) => current && reviews.some((item) => item.id === current) ? current : reviews[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load the review queue.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => items.filter((item) => {
    const statusMatch = statusFilter === "all" || (statusFilter === "actionable" ? ["pending", "decision_failed"].includes(item.status) || item.status.includes("in_progress") : item.status.toLowerCase().includes(statusFilter));
    const riskMatch = riskFilter === "all" || reviewRisk(item) === riskFilter;
    return statusMatch && riskMatch;
  }), [items, riskFilter, statusFilter]);

  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0] ?? null;
  const escalationReasons = selected
    ? (selected.escalation_reasons?.length ? selected.escalation_reasons : selected.reason.split(";").map((reason) => reason.trim()).filter(Boolean))
    : [];
  const inProgressDecision = selected?.status.includes("in_progress") ?? false;
  const canDecide = selected ? ["pending", "decision_failed"].includes(selected.status) || inProgressDecision : false;
  const retryingDecision = selected?.status === "decision_failed" || inProgressDecision;
  const decisionHistory = selected ? [...(selected.decision_history ?? [])].sort((left, right) => new Date(String(right.at ?? 0)).getTime() - new Date(String(left.at ?? 0)).getTime()) : [];

  useEffect(() => {
    setEditedResponse(selected ? stripMarkdownEmphasis(reviewResponse(selected)) : "");
    setNotes(selected?.reviewer_notes ?? "");
    setAcknowledged(false);
  }, [selected]);

  async function decide(action: "approve" | "reject" | "edit-and-approve") {
    if (!selected || saving || !acknowledged) return;
    setSaving(true);
    setError(null);
    try {
      await client.reviewAction(selected.id, action, {
        reviewer_notes: notes.trim() || undefined,
        edited_response: action === "edit-and-approve" ? editedResponse.trim() : undefined,
      });
      await load();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The review decision could not be saved.";
      await load();
      setError(`${message} The item remains recoverable; acknowledge the evidence and retry the decision.`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="page page--reviews">
      <PageHeader title="Review Queue" actions={<Button icon="refresh" onClick={() => void load()} disabled={loading}>Refresh</Button>} />
      {error ? <ErrorBanner message={error} retry={() => void load()} /> : null}
      <div className="review-layout">
        <section className="review-master">
          <div className="filter-toolbar">
            <label className="field"><span>Status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="actionable">Needs action</option><option value="all">All</option><option value="pending">Pending</option><option value="decision_failed">Retry available</option><option value="in_progress">In progress</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label>
            <label className="field"><span>Risk</span><select value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}><option value="all">All</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unknown">Unknown</option></select></label>
            <span className="filter-count">{filtered.length} results</span>
          </div>
          {loading ? <LoadingRows rows={7} /> : filtered.length ? (
            <div className="table-scroll review-table-wrap">
              <table className="data-table review-table">
                <thead><tr><th>Request</th><th>Review status</th><th>Request status</th><th>Risk</th><th>Reason</th><th>Confidence</th><th>Model</th><th>Age</th></tr></thead>
                <tbody>{filtered.map((item) => {
                  const active = item.id === selected?.id;
                  return (
                    <tr key={item.id} className={active ? "selected-row" : ""} onClick={() => setSelectedId(item.id)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter") setSelectedId(item.id); }}>
                      <td><button className="row-link" onClick={() => setSelectedId(item.id)}>{item.request_id.slice(0, 16)}</button><small>{new Date(item.created_at).toLocaleString()}</small></td>
                      <td><StatusMark tone={statusTone(item.status)}>{humanize(item.status)}</StatusMark></td>
                      <td><StatusMark tone={statusTone(item.request_status)}>{humanize(item.request_status)}</StatusMark></td>
                      <td><StatusMark tone={riskTone(reviewRisk(item))}>{reviewRisk(item)}</StatusMark></td>
                      <td>{item.reason}</td>
                      <td><span className="score-cell"><code>{reviewConfidence(item).toFixed(2)}</code><i><b style={{ width: `${reviewConfidence(item) * 100}%` }} /></i></span></td>
                      <td><code>{item.model ?? item.request?.model_used ?? "—"}</code></td>
                      <td>{new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(-Math.max(1, Math.round((Date.now() - new Date(item.created_at).getTime()) / 60000)), "minute")}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          ) : <EmptyState title="No matching reviews" message="Adjust the queue filters or submit a high-risk request." />}
        </section>
        <aside className="review-detail" aria-label="Review detail">
          {selected ? (
            <>
              <header className="review-detail__header"><div><code>{selected.request_id}</code><small>Review: {humanize(selected.status)}</small></div><div className="review-detail__statuses"><StatusMark tone={statusTone(selected.status)}>Review · {humanize(selected.status)}</StatusMark><StatusMark tone={statusTone(selected.request_status)}>Request · {humanize(selected.request_status)}</StatusMark><StatusMark tone={riskTone(reviewRisk(selected))}>{reviewRisk(selected)} risk</StatusMark></div></header>
              <section><h2>Original request</h2><div className="read-only-field">{selected.message ?? selected.request?.message ?? "Request text unavailable"}</div></section>
              <label className="field field--textarea"><span>Generated response (editable)</span><textarea value={editedResponse} onChange={(event) => setEditedResponse(event.target.value)} rows={7} maxLength={8000} /><small>{editedResponse.length} / 8000</small></label>
              <section><h2>Citations ({(selected.citations ?? selected.request?.citations ?? []).length})</h2><ol className="source-list source-list--compact">{(selected.citations ?? selected.request?.citations ?? []).map((citation, index) => <li key={`${citation.title}:${index}`}><span>{index + 1}</span><button type="button" className="source-link" onClick={() => setSelectedCitation(citation)}><strong>{citation.title}</strong><small>{citation.source}</small></button><div className="source-score"><code>{citation.score === undefined ? "—" : `${Math.round(citation.score * 100)}%`}</code><small>relevance</small></div></li>)}</ol></section>
              <section className="escalation-analysis"><h2>Why this request escalated</h2><p className="section-caption">Escalation is additive: classification, retrieval, tool approval and final confidence gates are evaluated after generation. Any blocking gate keeps the response from automatic release.</p><ol>{escalationReasons.map((reason) => { const explanation = escalationExplanation(reason, selected); return <li key={reason}><span className="escalation-index" /><div><strong>{explanation.title}</strong><p>{explanation.detail}</p><code>Trigger: {reason}</code></div></li>; })}</ol></section>
              <dl className="review-metadata review-metadata--four"><div><dt>Topic</dt><dd>{humanize(selected.topic ?? selected.request?.topic ?? selected.intent ?? selected.request?.intent)}</dd></div><div><dt>Intent type</dt><dd>{humanize(selected.intent ?? selected.request?.intent)}</dd></div><div><dt>Model</dt><dd>{selected.model ?? selected.request?.model_used ?? "—"}</dd></div><div><dt>Confidence</dt><dd>{reviewConfidence(selected).toFixed(2)}</dd></div></dl>
              <section><h2>Decision evidence</h2><dl className="definition-list definition-list--review"><div><dt>Topic</dt><dd>{selected.topic_reason ?? selected.request?.topic_reason ?? selected.classification_reason ?? selected.request?.classification_reason ?? "No classifier rationale was returned."}</dd></div><div><dt>Risk</dt><dd>{selected.risk_reason ?? selected.request?.risk_reason ?? "No risk rationale was returned."}{(selected.risk_factors ?? selected.request?.risk_factors)?.length ? ` Evidence: ${(selected.risk_factors ?? selected.request?.risk_factors)?.join(" · ")}` : ""}</dd></div><div><dt>Model route</dt><dd>{selected.route_reason ?? selected.request?.route_reason ?? "No route rationale was returned."}</dd></div></dl></section>
              {selected.status === "decision_failed" ? <section className="review-recovery" role="alert"><strong>Previous decision attempt failed safely</strong><p>{selected.decision_error ?? "The operation did not complete."} No active claim remains; the same action can be retried after reviewing the evidence.</p></section> : inProgressDecision ? <section className="review-recovery review-recovery--active"><strong>Decision is actively claimed</strong><p>Processing started {selected.decision_started_at ? new Date(selected.decision_started_at).toLocaleString() : "recently"}. You may retry after acknowledging the evidence: an active lease returns a conflict without repeating the side effect, while a stale lease is reclaimed by the same action.</p></section> : null}
              <label className="field field--textarea"><span>Reviewer notes</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} maxLength={2000} placeholder="Add internal review context…" /></label>
              <label className="acknowledgement"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>I reviewed the response and its evidence.</span></label>
              <div className="decision-actions"><Button onClick={() => void decide("approve")} disabled={!canDecide || !acknowledged || saving}>{retryingDecision ? "Retry approve" : "Approve"}</Button><Button variant="primary" onClick={() => void decide("edit-and-approve")} disabled={!canDecide || !acknowledged || !editedResponse.trim() || saving}>{retryingDecision ? "Retry edit & approve" : "Edit & approve"}</Button><Button variant="danger" onClick={() => void decide("reject")} disabled={!canDecide || !acknowledged || saving}>{retryingDecision ? "Retry reject" : "Reject"}</Button></div>
              <section className="decision-history"><h2>Decision history <span>Newest first</span></h2><ol>{decisionHistory.length ? decisionHistory.map((event, index) => <li key={`${String(event.at ?? "event")}:${index}`}><span className="trace-node" /><time>{event.at ? new Date(String(event.at)).toLocaleString() : "Time unavailable"}</time><p>{humanize(String(event.event ?? "decision event"))} · {humanize(String(event.action ?? "review"))} · {humanize(String(event.status ?? selected.status))}{event.error_type ? ` · ${String(event.error_type)}` : ""}</p></li>) : <li><span className="trace-node" /><time>{selected.resolved_at ? new Date(selected.resolved_at).toLocaleString() : "Current"}</time><p>{selected.status === "pending" ? "Awaiting reviewer decision." : `Decision state: ${selected.status.replaceAll("_", " ")}.`}{selected.reviewer_notes ? ` ${selected.reviewer_notes}` : ""}</p></li>}<li><span className="trace-node" /><time>{new Date(selected.created_at).toLocaleString()}</time><p>Automatically escalated after one or more release gates failed.</p></li></ol></section>
            </>
          ) : <EmptyState title="Select a review" message="Choose a queue item to inspect evidence and make a decision." />}
        </aside>
      </div>
      <SourceDocumentDialog citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
    </main>
  );
}
