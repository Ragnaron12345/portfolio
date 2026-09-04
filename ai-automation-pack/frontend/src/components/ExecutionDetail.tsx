import type { Execution, ExtractedField, ValidationResult } from "../types";
import { Icon } from "./Icon";
import { Timeline } from "./Timeline";
import {
  ReadableData,
  RiskTag,
  StatusMark,
  formatDuration,
  formatPercent,
  formatTime,
  humanize,
} from "./Ui";

function DetailHeader({ execution }: { execution: Execution }) {
  return (
    <header className="execution-detail__header">
      <div>
        <span className="eyeline">{execution.workflow}</span>
        <h2>{execution.execution_id}</h2>
        <p>{execution.decision_summary}</p>
      </div>
      <StatusMark status={execution.status} />
    </header>
  );
}

function MetaStrip({ execution }: { execution: Execution }) {
  return (
    <dl className="meta-strip">
      <div><dt>Correlation</dt><dd>{execution.correlation_id}</dd></div>
      <div><dt>Current stage</dt><dd>{humanize(execution.current_stage)}</dd></div>
      <div><dt>Started</dt><dd>{formatTime(execution.started_at, true)}</dd></div>
      <div><dt>Duration</dt><dd>{formatDuration(execution.duration_ms)}</dd></div>
      <div><dt>Retries</dt><dd>{execution.retry_count}</dd></div>
    </dl>
  );
}

function SupportDetail({ execution }: { execution: Execution }) {
  const classification = execution.classification;
  return (
    <div className="workflow-detail workflow-detail--support">
      <section className="detail-section">
        <h3>Original request</h3>
        <ReadableData value={execution.input} />
      </section>
      {classification ? (
        <section className="detail-section">
          <h3>AI classification</h3>
          <dl className="decision-grid">
            <div><dt>Category</dt><dd className="mono">{classification.category}</dd></div>
            <div><dt>Risk</dt><dd><RiskTag risk={classification.risk_level} /></dd></div>
            <div><dt>Confidence</dt><dd>{formatPercent(classification.confidence <= 1 ? classification.confidence * 100 : classification.confidence, 0)}</dd></div>
            <div><dt>Human review</dt><dd>{classification.needs_human ? "Required" : "Not required"}</dd></div>
          </dl>
          <div className="reason-block"><strong>Classification reason</strong><p>{classification.reason}</p></div>
          {classification.confidence_basis.length ? (
            <div className="confidence-basis"><strong>Confidence basis</strong><ul>{classification.confidence_basis.map((item) => <li key={item}>{item}</li>)}</ul></div>
          ) : null}
        </section>
      ) : null}
      <section className="detail-section">
        <h3>Decision</h3>
        <div className="decision-callout"><Icon name={execution.status.includes("review") ? "shield" : "check"} /><div><strong>{execution.decision_summary}</strong><p>{execution.decision_reason}</p></div></div>
      </section>
      {execution.generated_draft ? (
        <section className="detail-section">
          <h3>Grounded response</h3>
          <div className="response-copy">{execution.generated_draft}</div>
        </section>
      ) : null}
      <section className="detail-section">
        <h3>Policy sources</h3>
        {execution.sources.length ? (
          <div className="source-list">
            {execution.sources.map((source) => (
              <article className="source-row" key={source.id}>
                <Icon name="file" />
                <div><strong>{source.title}</strong>{source.excerpt ? <p>{source.excerpt}</p> : null}</div>
                <span>{formatPercent(source.relevance <= 1 ? source.relevance * 100 : source.relevance, 0)} relevant</span>
              </article>
            ))}
          </div>
        ) : <p className="muted-copy">No knowledge sources were needed for this decision.</p>}
      </section>
    </div>
  );
}

function FieldTable({ fields }: { fields: ExtractedField[] }) {
  if (!fields.length) return <p className="muted-copy">No validated fields are available.</p>;
  return (
    <div className="field-table" role="table" aria-label="Extracted invoice fields">
      <div className="field-table__header" role="row"><span role="columnheader">Field</span><span role="columnheader">Extracted value</span><span role="columnheader">Confidence</span></div>
      {fields.map((field) => (
        <div className="field-table__row" role="row" key={field.name}>
          <span role="cell">{humanize(field.name)}</span><strong role="cell">{field.value}</strong><span role="cell">{field.confidence === undefined ? "—" : formatPercent(field.confidence <= 1 ? field.confidence * 100 : field.confidence, 0)}</span>
        </div>
      ))}
    </div>
  );
}

function ValidationList({ validations }: { validations: ValidationResult[] }) {
  if (!validations.length) return <p className="muted-copy">Validation checks have not been recorded.</p>;
  return (
    <div className="validation-list">
      {validations.map((validation) => (
        <article className={`validation-row validation-row--${validation.passed ? "passed" : "failed"}`} key={validation.rule}>
          <span className="validation-row__icon"><Icon name={validation.passed ? "check" : "error"} /></span>
          <div><strong>{humanize(validation.rule)}</strong><p>{validation.message}</p>{validation.expected || validation.actual ? <small>Expected: {validation.expected ?? "—"} · Actual: {validation.actual ?? "—"}</small> : null}</div>
          <span>{validation.passed ? "Passed" : "Review"}</span>
        </article>
      ))}
    </div>
  );
}

function InvoiceDetail({ execution }: { execution: Execution }) {
  return (
    <div className="workflow-detail workflow-detail--invoice">
      <section className="detail-section invoice-origin">
        <h3>Original document</h3>
        <div className="document-preview"><Icon name="file" /><div><strong>{execution.original_file ?? "Invoice document"}</strong><span>Source preserved with this execution</span></div></div>
        <ReadableData value={execution.input} />
      </section>
      <section className="detail-section"><h3>Extracted fields</h3><FieldTable fields={execution.extracted_fields} /></section>
      <section className="detail-section"><h3>Deterministic validation</h3><ValidationList validations={execution.validations} /></section>
      <section className="detail-section">
        <h3>Decision</h3>
        <div className="decision-callout"><Icon name={execution.validations.some((item) => !item.passed) ? "warning" : "check"} /><div><strong>{execution.decision_summary}</strong><p>{execution.decision_reason}</p></div></div>
      </section>
    </div>
  );
}

function StringItems({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? <ul className="evidence-list">{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted-copy">{empty}</p>;
}

function IncidentDetail({ execution }: { execution: Execution }) {
  const summary = execution.incident_summary;
  return (
    <div className="workflow-detail workflow-detail--incident">
      <section className="detail-section"><h3>Incoming event</h3><ReadableData value={execution.input} /></section>
      {execution.deduplicated_into ? (
        <div className="dedupe-callout"><Icon name="retry" /><div><strong>Deduplicated into {execution.deduplicated_into}</strong><p>No second Jira incident was created. The matching incident record was updated.</p></div></div>
      ) : null}
      {summary ? (
        <section className="detail-section incident-summary">
          <div className="incident-summary__title"><div><span className="eyeline">Structured incident summary</span><h3>{summary.title}</h3></div><span>{formatPercent(summary.confidence <= 1 ? summary.confidence * 100 : summary.confidence, 0)} confidence</span></div>
          <div className="incident-summary__grid">
            <div><h4>Observed symptoms</h4><StringItems items={summary.observed_symptoms} empty="No symptoms recorded." /></div>
            <div><h4>Probable impact</h4><p>{summary.probable_impact}</p></div>
            <div><h4>Possible causes</h4><StringItems items={summary.possible_causes} empty="No hypotheses generated." /></div>
            <div><h4>Suggested investigation</h4><StringItems items={summary.suggested_investigation_steps} empty="No investigation steps generated." /></div>
          </div>
          <p className="hypothesis-note"><Icon name="shield" /> Possible causes are hypotheses only; no root cause is presented as confirmed.</p>
        </section>
      ) : null}
      <section className="detail-section">
        <h3>External actions</h3>
        {execution.external_actions.length ? <div className="action-list">{execution.external_actions.map((action, index) => <article key={`${action.system}-${action.reference ?? index}`}><span><Icon name={action.status.includes("fail") ? "error" : "check"} /></span><div><strong>{action.system} · {action.action}</strong><p>{action.message ?? action.status}</p></div>{action.reference ? <code>{action.reference}</code> : null}</article>)}</div> : <p className="muted-copy">No external action was executed.</p>}
      </section>
    </div>
  );
}

export function ExecutionDetail({ execution, showTimeline = true }: { execution: Execution; showTimeline?: boolean }) {
  return (
    <article className="execution-detail">
      <DetailHeader execution={execution} />
      <MetaStrip execution={execution} />
      {execution.error ? <div className="execution-error" role="alert"><Icon name="error" /><div><strong>Execution failed</strong><p>{execution.error}</p></div></div> : null}
      <div className={showTimeline ? "execution-detail__layout" : "execution-detail__layout execution-detail__layout--single"}>
        <div className="execution-detail__body">
          {execution.workflow_key === "support" ? <SupportDetail execution={execution} /> : null}
          {execution.workflow_key === "invoice" ? <InvoiceDetail execution={execution} /> : null}
          {execution.workflow_key === "incident" ? <IncidentDetail execution={execution} /> : null}
        </div>
        {showTimeline ? <aside className="execution-detail__timeline"><h3>Execution timeline</h3><Timeline events={execution.events} /></aside> : null}
      </div>
    </article>
  );
}
