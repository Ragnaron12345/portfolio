import type {
  Approval,
  AuditEvent,
  Classification,
  DemoScenario,
  Execution,
  ExecutionEvent,
  ExtractedField,
  HealthStatus,
  IncidentSummary,
  ListResponse,
  Metrics,
  MockRecord,
  MockSystemKey,
  SourceEvidence,
  ValidationResult,
  WorkflowKey,
  WorkflowMetric,
} from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";

type JsonRecord = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function record(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function records(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record).filter((entry) => Object.keys(entry).length > 0) : [];
}

function first(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined);
}

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function readableError(value: unknown): string {
  const direct = text(value).trim();
  if (direct) return direct;

  const item = record(value);
  if (!Object.keys(item).length) return "Execution failed without a recorded reason.";

  const code = text(first(item.code, item.error_code, item.type)).trim();
  const nestedError = record(item.error);
  const details = record(first(item.details, item.detail));
  const message = text(first(
    item.message,
    item.reason,
    nestedError.message,
    nestedError.reason,
    details.message,
    details.reason,
    details.detail,
    text(item.detail),
  )).trim();
  const field = text(first(details.field, item.field)).trim();

  const parts = [code, message, field ? `Field: ${field}` : ""].filter(Boolean);
  return [...new Set(parts)].join(" · ") || "Execution failed without a recorded reason.";
}

function numberValue(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function booleanValue(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value.toLowerCase() === "true";
  return fallback;
}

function percentage(value: unknown): number {
  const parsed = numberValue(value);
  return parsed >= 0 && parsed <= 1 ? parsed * 100 : parsed;
}

function timestamp(value: unknown): string {
  const raw = text(value);
  if (!raw) return new Date(0).toISOString();
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(raw) ? raw : `${raw}Z`;
}

function optionalTimestamp(value: unknown): string | null {
  return value === null || value === undefined || value === "" ? null : timestamp(value);
}

function safeRecord(value: unknown): Record<string, unknown> {
  return record(value);
}

function workflowKey(value: unknown): WorkflowKey {
  const normalized = text(value).toLowerCase();
  if (normalized.includes("invoice")) return "invoice";
  if (normalized.includes("incident")) return "incident";
  return "support";
}

function workflowName(value: unknown): string {
  const key = workflowKey(value);
  if (key === "invoice") return "Invoice Processing";
  if (key === "incident") return "Incident Intelligence";
  return "AI Support Triage";
}

function normalizeClassification(value: unknown): Classification | undefined {
  const item = record(value);
  if (!Object.keys(item).length) return undefined;
  const confidence = record(item.confidence_details ?? item.confidence_basis);
  const basis = Array.isArray(item.confidence_basis)
    ? item.confidence_basis.map((entry) => text(entry)).filter(Boolean)
    : Object.entries(confidence).map(([key, entry]) => `${key.replaceAll("_", " ")}: ${text(entry)}`).filter((entry) => !entry.endsWith(": "));
  return {
    category: text(item.category, "Unclassified"),
    risk_level: text(first(item.risk_level, item.risk), "unknown"),
    confidence: numberValue(item.confidence),
    reason: text(first(item.reason, item.classification_reason), "No classification reason recorded."),
    needs_human: booleanValue(first(item.needs_human, item.requires_review)),
    confidence_basis: basis,
  };
}

function normalizeSources(value: unknown): SourceEvidence[] {
  return records(value).map((item, index) => ({
    id: text(first(item.id, item.source_id), `source-${index + 1}`),
    title: text(first(item.title, item.name, item.source), `Policy source ${index + 1}`),
    excerpt: text(first(item.excerpt, item.content, item.chunk, item.text)),
    relevance: numberValue(first(item.relevance, item.relevance_score, item.score)),
  }));
}

function normalizeFields(value: unknown): ExtractedField[] {
  if (Array.isArray(value)) {
    return records(value).map((item) => ({
      name: text(first(item.name, item.field, item.label), "Field"),
      value: text(first(item.value, item.extracted_value), "Not provided"),
      confidence: item.confidence === undefined ? undefined : numberValue(item.confidence),
    }));
  }
  const fields = record(value);
  const sharedConfidence = fields.confidence === undefined ? undefined : numberValue(fields.confidence);
  return Object.entries(fields).filter(([name]) => name !== "confidence").map(([name, raw]) => {
    const nested = record(raw);
    return {
      name,
      value: Object.keys(nested).length ? text(first(nested.value, nested.text), "Not provided") : text(raw, "Not provided"),
      confidence: nested.confidence === undefined ? sharedConfidence : numberValue(nested.confidence),
    };
  });
}

function normalizeValidations(value: unknown): ValidationResult[] {
  const direct = records(value);
  if (direct.length) {
    return direct.map((item, index) => ({
      rule: text(first(item.rule, item.name, item.check), `Validation ${index + 1}`),
      passed: booleanValue(first(item.passed, item.valid, item.success)),
      message: text(first(item.message, item.reason, item.detail), "No validation detail recorded."),
      expected: item.expected === undefined ? undefined : text(item.expected),
      actual: item.actual === undefined ? undefined : text(item.actual),
    }));
  }
  const validation = record(value);
  if (!Object.keys(validation).length) return [];
  const checks = records(first(validation.checks, validation.results));
  if (checks.length) return normalizeValidations(checks);
  const failures = stringList(validation.failures);
  if (failures.length) {
    return failures.map((message, index) => ({
      rule: index === 0 && message.toLowerCase().includes("total") ? "invoice_arithmetic" : `deterministic_check_${index + 1}`,
      passed: false,
      message,
    }));
  }
  const passed = booleanValue(validation.valid);
  return [{
    rule: "deterministic_checks",
    passed,
    message: text(validation.reason, passed ? "All required fields, dates, currency and arithmetic checks passed." : "Deterministic validation requires review."),
  }];
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : [];
}

function normalizeIncidentSummary(value: unknown): IncidentSummary | undefined {
  const item = record(value);
  if (!Object.keys(item).length) return undefined;
  return {
    title: text(item.title, "Incident summary"),
    observed_symptoms: stringList(item.observed_symptoms),
    probable_impact: text(item.probable_impact, "Impact is still being assessed."),
    possible_causes: stringList(item.possible_causes),
    suggested_investigation_steps: stringList(item.suggested_investigation_steps),
    confidence: numberValue(item.confidence),
  };
}

export function normalizeEvent(raw: unknown, index = 0): ExecutionEvent {
  const item = record(raw);
  const status = text(first(item.status, item.state), "completed").toLowerCase();
  const stage = text(first(item.stage, item.event_type, item.type), `stage-${index + 1}`);
  return {
    id: text(first(item.id, item.event_id), `${stage}-${index}`),
    stage,
    label: text(first(item.label, item.name, item.title), stage.replaceAll("_", " ")),
    status,
    occurred_at: item.occurred_at || item.created_at || item.started_at ? timestamp(first(item.occurred_at, item.created_at, item.started_at)) : undefined,
    completed_at: item.completed_at ? timestamp(item.completed_at) : undefined,
    duration_ms: item.duration_ms === undefined ? undefined : numberValue(item.duration_ms),
    message: item.message || item.reason || item.error
      ? (typeof first(item.message, item.reason, item.error) === "object" ? readableError(first(item.message, item.reason, item.error)) : text(first(item.message, item.reason, item.error)))
      : undefined,
    retry: item.retry === undefined && item.attempt === undefined ? undefined : numberValue(first(item.retry, item.attempt)),
  };
}

export function normalizeExecution(raw: unknown): Execution {
  const item = record(raw);
  const detail = record(first(item.details, item.detail, item.output, item.result));
  const decisionSummary = record(first(item.decision_summary, detail.decision_summary));
  const decision = { ...record(detail.decision), ...decisionSummary };
  const classification = normalizeClassification(first(item.classification, detail.classification, decision.classification));
  const sourceValue = first(item.sources, item.retrieved_sources, detail.sources, detail.retrieved_sources, decision.sources);
  const invoice = record(first(item.invoice, detail.invoice, detail.extraction, item.extraction, decision.document));
  const incident = record(first(item.incident, detail.incident));
  const actionValue = first(item.external_actions, detail.external_actions, item.actions, detail.actions);
  const eventsValue = first(item.events, item.timeline, detail.events, detail.timeline);
  const aiCallsValue = first(item.ai_calls, detail.ai_calls);
  const rawWorkflow = first(item.workflow, item.workflow_name, item.workflow_type, item.type);
  const key = workflowKey(rawWorkflow);
  const duration = first(item.duration_ms, detail.duration_ms);
  const parsedEvents = Array.isArray(eventsValue) ? eventsValue.map(normalizeEvent) : [];
  const executionStatus = text(item.status, "received").toLowerCase();
  const normalizedEvents = parsedEvents.map((event, index) => {
    if (event.status === "failed") return event;
    if (index < parsedEvents.length - 1) return { ...event, status: "completed" };
    if (executionStatus === "completed" || executionStatus === "completed_with_warning") return { ...event, status: "completed" };
    return { ...event, status: executionStatus };
  });

  return {
    execution_id: text(first(item.execution_id, item.id), "unknown-execution"),
    correlation_id: text(first(item.correlation_id, item.correlation), "not-recorded"),
    workflow: workflowName(rawWorkflow),
    workflow_key: key,
    current_stage: text(first(item.current_stage, item.stage), "received"),
    status: executionStatus,
    started_at: timestamp(first(item.started_at, item.created_at)),
    completed_at: optionalTimestamp(item.completed_at),
    duration_ms: duration === null || duration === undefined ? null : numberValue(duration),
    error: item.error === null || item.error === undefined ? null : readableError(item.error),
    decision_summary: text(first(decision.outcome, decision.decision, item.decision, decision.summary, decision.action), "Decision pending").replaceAll("_", " "),
    decision_reason: text(first(item.decision_reason, decision.reason, detail.decision_reason, classification?.reason), "No decision reason recorded."),
    retry_count: numberValue(first(item.retry_count, item.retries, detail.retry_count)),
    ai_attempt_count: Array.isArray(aiCallsValue) ? aiCallsValue.length : null,
    input: safeRecord(first(item.input_data, item.input, item.request, item.payload, detail.input)),
    classification,
    sources: normalizeSources(sourceValue),
    generated_draft: text(first(item.generated_draft, item.draft, decision.draft, detail.generated_draft, detail.response)) || undefined,
    extracted_fields: normalizeFields(first(item.extracted_fields, decision.extracted_fields, invoice.fields, invoice.extracted_fields, detail.extracted_fields)),
    validations: normalizeValidations(first(item.validations, item.validation_results, decision.validation, invoice.validations, detail.validation_results)),
    original_file: text(first(item.original_file, item.file_name, invoice.name, invoice.file_name, record(item.input_data).document_name)) || undefined,
    incident_summary: normalizeIncidentSummary(first(item.incident_summary, decision.summary, incident.summary, detail.incident_summary, detail.summary)),
    deduplicated_into: text(first(item.deduplicated_into, decision.outcome === "deduplicated" ? decision.incident_key : undefined, incident.deduplicated_into, detail.deduplicated_into)) || undefined,
    external_actions: records(actionValue).map((action) => ({
      system: text(first(action.system, action.target), "External system"),
      action: text(first(action.action, action.type), "Action"),
      status: text(action.status, action.success === true ? "completed" : action.success === false ? "failed" : "unknown"),
      reference: text(first(action.reference, action.external_id, record(action.response).id, action.id)) || undefined,
      message: text(first(action.message, record(action.response).message)) || undefined,
    })),
    events: normalizedEvents,
  };
}

function unwrapList(value: unknown): { items: unknown[]; total: number } {
  if (Array.isArray(value)) return { items: value, total: value.length };
  const payload = record(value);
  const items = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.results)
      ? payload.results
      : Array.isArray(payload.data)
        ? payload.data
        : [];
  return { items, total: numberValue(payload.total, items.length) };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let details: unknown;
    try {
      details = await response.json();
    } catch {
      details = undefined;
    }
    const envelope = record(details);
    const detail = first(envelope.detail, envelope.message, envelope.error);
    const nestedDetail = record(detail);
    const message = typeof detail === "string"
      ? detail
      : text(first(nestedDetail.message, nestedDetail.detail), `Request failed with status ${response.status}.`);
    throw new ApiError(message, response.status, details);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestWithFallback<T>(paths: string[], init?: RequestInit): Promise<T> {
  let error: unknown;
  for (const path of paths) {
    try {
      return await request<T>(path, init);
    } catch (candidate) {
      error = candidate;
      if (!(candidate instanceof ApiError) || candidate.status !== 404) throw candidate;
    }
  }
  throw error;
}

function normalizeWorkflowMetric(raw: unknown): WorkflowMetric {
  const item = record(raw);
  const rawWorkflow = first(item.workflow, item.workflow_name, item.name);
  const executions = numberValue(first(item.executions, item.total, item.count));
  const successCount = numberValue(item.success);
  const reviewCount = numberValue(item.review);
  const failureCount = numberValue(first(item.failures, item.failure));
  const successRate = item.success_rate !== undefined ? percentage(item.success_rate) : executions ? successCount / executions * 100 : 0;
  const reviewRate = item.review_rate !== undefined ? percentage(item.review_rate) : executions ? reviewCount / executions * 100 : 0;
  const failureRate = item.failure_rate !== undefined ? percentage(item.failure_rate) : executions ? failureCount / executions * 100 : 0;
  return {
    workflow: workflowName(rawWorkflow),
    workflow_key: workflowKey(rawWorkflow),
    executions,
    success_rate: successRate,
    review_rate: reviewRate,
    failure_rate: failureRate,
    average_latency_ms: numberValue(first(item.average_latency_ms, item.avg_latency_ms, item.average_latency)),
    p95_latency_ms: item.p95_latency_ms === undefined && item.p95_latency === undefined
      ? undefined
      : numberValue(first(item.p95_latency_ms, item.p95_latency)),
    status: text(item.status, failureRate >= 20 ? "unhealthy" : failureRate > 0 || reviewRate >= 40 ? "degraded" : "healthy").toLowerCase(),
    trend: Array.isArray(item.trend) ? item.trend.map((entry) => numberValue(entry)) : [],
  };
}

function normalizeMetrics(raw: unknown): Metrics {
  const item = record(raw);
  const totals = record(first(item.totals, item.summary));
  const value = { ...totals, ...item };
  const workflowValues = first(value.workflows, value.per_workflow, value.workflow_metrics);
  const workflows = Array.isArray(workflowValues)
    ? workflowValues.map(normalizeWorkflowMetric)
    : Object.entries(record(workflowValues)).map(([name, metric]) => normalizeWorkflowMetric({ workflow: name, ...record(metric) }));
  return {
    executions_today: numberValue(first(value.executions_today, value.total_executions, value.executions)),
    success_rate: percentage(first(value.success_rate, value.success_rate_percent)),
    failure_rate: percentage(first(value.failure_rate, value.failure_rate_percent, value.error_rate)),
    review_rate: percentage(first(value.review_rate, value.review_rate_percent)),
    average_latency_ms: numberValue(first(value.average_latency_ms, value.avg_latency_ms, value.average_latency)),
    p95_latency_ms: numberValue(first(value.p95_latency_ms, value.p95_latency)),
    pending_reviews: numberValue(first(value.pending_reviews, value.review_queue_size)),
    workflows,
  };
}

function normalizeApproval(raw: unknown): Approval {
  const item = record(raw);
  const originalInput = safeRecord(item.original_input);
  const context = { ...originalInput, ...safeRecord(first(item.decision_context, item.context)) };
  const embedded = first(item.execution, context.execution);
  const historyValue = first(item.history, item.decision_history, item.decisions);
  return {
    id: text(first(item.id, item.approval_id), "unknown-review"),
    workflow: workflowName(first(item.workflow, item.workflow_name)),
    execution_id: text(first(item.execution_id, record(embedded).execution_id, record(embedded).id), "unknown-execution"),
    title: text(first(item.title, context.title, context.subject, context.document_name, context.service), `${text(first(item.workflow, item.workflow_name), "Workflow")} review`),
    reason: text(item.reason, "This execution requires an operator decision."),
    status: text(item.status, "pending").toLowerCase(),
    created_at: timestamp(item.created_at),
    resolved_at: optionalTimestamp(item.resolved_at),
    reviewer_note: text(first(item.reviewer_note, item.note)),
    decision_context: context,
    execution: Object.keys(record(embedded)).length ? normalizeExecution(embedded) : undefined,
    history: records(historyValue).map((decision) => ({
      decision: text(first(decision.decision, decision.action), "unknown"),
      reviewer: text(first(decision.reviewer, decision.actor), "Operator"),
      note: text(first(decision.note, decision.reviewer_note)),
      created_at: timestamp(first(decision.created_at, decision.resolved_at)),
    })).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
  };
}

function normalizeAudit(raw: unknown): AuditEvent {
  const item = record(raw);
  const context = { ...record(item.details), ...record(item.context) };
  const rawWorkflow = first(item.workflow, item.workflow_name, context.workflow, context.webhook);
  return {
    id: text(first(item.id, item.event_id), "unknown-event"),
    execution_id: text(item.execution_id, "not-recorded"),
    correlation_id: text(first(item.correlation_id, context.correlation_id), "not-recorded"),
    workflow: text(rawWorkflow) ? workflowName(rawWorkflow) : "System",
    event_type: text(first(item.event_type, item.type), "event"),
    actor: text(item.actor, "system"),
    action: text(first(item.action, item.message), "Recorded event"),
    outcome: text(first(item.outcome, item.status), "recorded"),
    reason: text(first(item.reason, item.detail)),
    created_at: timestamp(item.created_at),
  };
}

const executionIdentityCache = new Map<string, Promise<{ workflow: string; correlation_id: string } | undefined>>();

function getExecutionIdentity(executionId: string): Promise<{ workflow: string; correlation_id: string } | undefined> {
  const cached = executionIdentityCache.get(executionId);
  if (cached) return cached;
  const pending = request<unknown>(`/executions/${encodeURIComponent(executionId)}`)
    .then(normalizeExecution)
    .then((execution) => ({ workflow: execution.workflow, correlation_id: execution.correlation_id }))
    .catch(() => {
      executionIdentityCache.delete(executionId);
      return undefined;
    });
  executionIdentityCache.set(executionId, pending);
  return pending;
}

function humanizeKey(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function normalizeMockRecord(raw: unknown, index: number): MockRecord {
  const item = record(raw);
  const hidden = new Set(["id", "ticket_id", "issue_id", "invoice_id", "message_id", "execution_id", "originating_execution_id", "created_at", "status", "title", "subject", "summary"]);
  const fields = Object.entries(item).flatMap(([key, value]) => {
    if (hidden.has(key) || typeof value === "object" || value === null || value === undefined) return [];
    return [{ label: humanizeKey(key), value: text(value) }];
  }).slice(0, 6);
  return {
    id: text(first(item.id, item.ticket_id, item.issue_id, item.invoice_id, item.message_id), `record-${index + 1}`),
    execution_id: text(first(item.execution_id, item.originating_execution_id), "not-recorded"),
    title: text(first(item.title, item.subject, item.summary, item.vendor), "External record"),
    status: text(item.status, "recorded"),
    created_at: timestamp(item.created_at),
    fields,
  };
}

function normalizeScenario(raw: unknown): DemoScenario {
  const item = record(raw);
  const rawWorkflow = first(item.workflow, item.workflow_key, item.type);
  return {
    id: text(first(item.id, item.scenario_id), "scenario"),
    workflow: workflowKey(rawWorkflow),
    name: text(first(item.name, item.title), "Demo scenario"),
    description: text(item.description, "Run this workflow with deterministic demo data."),
    outcome: text(first(item.outcome, item.expected_outcome, item.expected), "Execution created"),
    risk: text(item.risk) || undefined,
  };
}

export const client = {
  getHealth(): Promise<HealthStatus> {
    return request<unknown>("/health").then((raw) => {
      const value = record(raw);
      const status = text(first(value.status, value.state), "unhealthy").toLowerCase();
      return {
        status,
        label: text(value.message, status === "healthy" || status === "ok" ? "API & database operational" : "API attention required"),
        checked_at: timestamp(first(value.checked_at, value.timestamp, new Date().toISOString())),
      };
    });
  },

  async getExecutions(options: { workflow?: string; status?: string; limit?: number } = {}): Promise<ListResponse<Execution>> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options)) {
      if (value !== undefined && value !== "") query.set(key, String(value));
    }
    const payload = unwrapList(await request<unknown>(`/executions${query.size ? `?${query}` : ""}`));
    return { items: payload.items.map(normalizeExecution), total: payload.total };
  },

  getExecution(id: string): Promise<Execution> {
    return request<unknown>(`/executions/${encodeURIComponent(id)}`).then(normalizeExecution);
  },

  async getExecutionEvents(id: string): Promise<ExecutionEvent[]> {
    const payload = unwrapList(await request<unknown>(`/executions/${encodeURIComponent(id)}/events`));
    return payload.items.map(normalizeEvent);
  },

  getMetrics(): Promise<Metrics> {
    return request<unknown>("/metrics").then(normalizeMetrics);
  },

  async getApprovals(status = "pending"): Promise<ListResponse<Approval>> {
    if (status === "resolved") {
      const [approved, rejected] = await Promise.all([
        request<unknown>("/approvals?status=approved").then(unwrapList),
        request<unknown>("/approvals?status=rejected").then(unwrapList),
      ]);
      const items = [...approved.items, ...rejected.items]
        .map(normalizeApproval)
        .sort((a, b) => Date.parse(b.resolved_at ?? b.created_at) - Date.parse(a.resolved_at ?? a.created_at));
      return { items, total: approved.total + rejected.total };
    }
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    const payload = unwrapList(await request<unknown>(`/approvals${query}`));
    return { items: payload.items.map(normalizeApproval), total: payload.total };
  },

  getApproval(id: string): Promise<Approval> {
    return request<unknown>(`/approvals/${encodeURIComponent(id)}`).then(normalizeApproval);
  },

  async decideApproval(id: string, decision: "approved" | "rejected", note: string): Promise<Approval> {
    const encoded = encodeURIComponent(id);
    try {
      const result = await request<unknown>(`/approvals/${encoded}/${decision === "approved" ? "approve" : "reject"}`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "Ops Operator", note }),
      });
      return normalizeApproval(result);
    } catch (candidate) {
      if (!(candidate instanceof ApiError) || candidate.status !== 404) throw candidate;
      return request<unknown>(`/approvals/${encoded}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reviewer: "Ops Operator", note }),
      }).then(normalizeApproval);
    }
  },

  async getAuditEvents(options: { workflow?: string; outcome?: string; limit?: number } = {}): Promise<ListResponse<AuditEvent>> {
    const query = new URLSearchParams();
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    const suffix = query.size ? `?${query}` : "";
    const payload = unwrapList(await requestWithFallback<unknown>([`/audit/events${suffix}`, `/audit${suffix}`]));
    const items = payload.items.map(normalizeAudit);
    const identities = new Map(await Promise.all(
      [...new Set(items.map((item) => item.execution_id).filter((id) => id !== "not-recorded"))]
        .map(async (id) => [id, await getExecutionIdentity(id)] as const),
    ));
    return {
      items: items.map((item) => {
        const identity = identities.get(item.execution_id);
        if (!identity) return item;
        return {
          ...item,
          workflow: item.workflow === "System" ? identity.workflow : item.workflow,
          correlation_id: item.correlation_id === "not-recorded" ? identity.correlation_id : item.correlation_id,
        };
      }),
      total: payload.total,
    };
  },

  async getMockRecords(system: MockSystemKey): Promise<ListResponse<MockRecord>> {
    const paths: Record<MockSystemKey, string[]> = {
      tickets: ["/mock/crm/tickets", "/mock/tickets"],
      incidents: ["/mock/jira/issues", "/mock/incidents"],
      messages: ["/mock/slack/messages", "/mock/messages"],
      invoices: ["/mock/erp/invoices", "/mock/invoices"],
    };
    const payload = unwrapList(await requestWithFallback<unknown>(paths[system]));
    return { items: payload.items.map(normalizeMockRecord), total: payload.total };
  },

  async getDemoScenarios(): Promise<DemoScenario[]> {
    const payload = unwrapList(await request<unknown>("/demo/scenarios"));
    return payload.items.map(normalizeScenario);
  },

  runDemoScenario(id: string): Promise<Execution> {
    return request<unknown>(`/demo/scenarios/${encodeURIComponent(id)}/run`, { method: "POST" }).then(normalizeExecution);
  },
};
