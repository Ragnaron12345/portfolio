import type {
  AvailableModel,
  Channel,
  EvaluationMetricSet,
  EvaluationRun,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  MetricsSummary,
  ModelMetric,
  RequestResult,
  ReviewItem,
  RoutingStrategy,
} from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";

type JsonObject = Record<string, unknown>;

function asRecord(value: unknown): JsonObject {
  return typeof value === "object" && value !== null ? value as JsonObject : {};
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asOptionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asOptionalBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

export function normalizeUtcTimestamp(value: unknown): string {
  const timestamp = String(value ?? new Date(0).toISOString());
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp) ? timestamp : `${timestamp}Z`;
}

function normalizeRequest(raw: unknown): RequestResult {
  const value = asRecord(raw);
  const confidenceDetails = asRecord(value.confidence_details);
  const decisionFactors = asRecord(value.decision_factors);
  const rawCalls = Array.isArray(value.tool_calls) ? value.tool_calls : [];
  const rawAttempts = Array.isArray(value.provider_attempts) ? value.provider_attempts : [];
  return {
    request_id: String(value.request_id ?? ""),
    trace_id: value.trace_id ? String(value.trace_id) : undefined,
    status: String(value.status ?? "unknown"),
    response: value.response === null || value.response === undefined ? null : String(value.response),
    citations: (Array.isArray(value.citations) ? value.citations : []) as RequestResult["citations"],
    confidence: asNumber(value.confidence),
    model_used: value.model_used === null || value.model_used === undefined ? null : String(value.model_used),
    requires_review: Boolean(value.requires_review),
    topic: value.topic ? String(value.topic) : undefined,
    topic_reason: value.topic_reason ? String(value.topic_reason) : undefined,
    intent: value.intent ? String(value.intent) : undefined,
    risk_level: value.risk_level as RequestResult["risk_level"],
    risk_reason: value.risk_reason ? String(value.risk_reason) : undefined,
    risk_factors: (Array.isArray(value.risk_factors) ? value.risk_factors : []).map((factor) => String(factor)),
    classification_reason: value.classification_reason ? String(value.classification_reason) : undefined,
    needs_retrieval: Boolean(value.needs_retrieval),
    needs_tools: Boolean(value.needs_tools),
    route_reason: value.route_reason ? String(value.route_reason) : undefined,
    latency_ms: asNumber(value.latency_ms),
    estimated_cost: asNumber(value.estimated_cost),
    tokens_in: asNumber(value.tokens_in ?? value.prompt_tokens),
    tokens_out: asNumber(value.tokens_out ?? value.completion_tokens),
    confidence_details: confidenceDetails,
    decision_factors: decisionFactors,
    escalation_reasons: (Array.isArray(value.escalation_reasons) ? value.escalation_reasons : [])
      .map((reason) => String(reason)),
    provider_attempts: rawAttempts.map((entry) => {
      const attempt = asRecord(entry);
      return {
        id: attempt.id ? String(attempt.id) : undefined,
        provider: String(attempt.provider ?? "unknown"),
        model: String(attempt.model ?? "unknown"),
        purpose: attempt.purpose ? String(attempt.purpose) : undefined,
        route_reason: attempt.route_reason === null || attempt.route_reason === undefined ? null : String(attempt.route_reason),
        prompt_tokens: asNumber(attempt.prompt_tokens),
        completion_tokens: asNumber(attempt.completion_tokens),
        latency_ms: asNumber(attempt.latency_ms),
        estimated_cost: asNumber(attempt.estimated_cost),
        retries: asNumber(attempt.retries),
        success: Boolean(attempt.success),
        error: attempt.error === null || attempt.error === undefined ? null : String(attempt.error),
        created_at: attempt.created_at ? normalizeUtcTimestamp(attempt.created_at) : undefined,
      };
    }),
    stage_timings: asRecord(value.stage_timings) as Record<string, number>,
    created_at: value.created_at ? normalizeUtcTimestamp(value.created_at) : undefined,
    completed_at: value.completed_at === null || value.completed_at === undefined ? null : normalizeUtcTimestamp(value.completed_at),
    channel: value.channel as RequestResult["channel"],
    message: value.message ? String(value.message) : undefined,
    tool_calls: rawCalls.map((entry) => {
      const call = asRecord(entry);
      return {
        id: call.id ? String(call.id) : undefined,
        tool_name: String(call.tool_name ?? "unknown_tool"),
        arguments: asRecord(call.arguments ?? call.arguments_json),
        result: call.result === null || call.result_json === null ? null : asRecord(call.result ?? call.result_json),
        status: String(call.status ?? "unknown"),
        latency_ms: asNumber(call.latency_ms),
        requires_approval: Boolean(call.requires_approval),
        error: call.error === null || call.error === undefined ? null : String(call.error),
      };
    }),
  };
}

function normalizeReview(raw: unknown): ReviewItem {
  const value = asRecord(raw);
  return {
    id: String(value.id ?? ""),
    request_id: String(value.request_id ?? ""),
    reason: String(value.reason ?? "Review required"),
    status: String(value.status ?? "pending"),
    reviewer_notes: value.reviewer_notes === null || value.reviewer_notes === undefined ? null : String(value.reviewer_notes),
    edited_response: value.edited_response === null || value.edited_response === undefined ? null : String(value.edited_response),
    created_at: normalizeUtcTimestamp(value.created_at),
    resolved_at: value.resolved_at === null || value.resolved_at === undefined ? null : normalizeUtcTimestamp(value.resolved_at),
    message: value.original_message ? String(value.original_message) : undefined,
    response: value.original_response === null || value.original_response === undefined ? undefined : String(value.original_response),
    confidence: asNumber(value.confidence),
    risk_level: value.risk_level as ReviewItem["risk_level"],
    model: value.model ? String(value.model) : undefined,
    topic: value.topic ? String(value.topic) : undefined,
    topic_reason: value.topic_reason ? String(value.topic_reason) : undefined,
    intent: value.intent ? String(value.intent) : undefined,
    risk_reason: value.risk_reason ? String(value.risk_reason) : undefined,
    risk_factors: (Array.isArray(value.risk_factors) ? value.risk_factors : []).map((factor) => String(factor)),
    citations: (Array.isArray(value.citations) ? value.citations : []) as ReviewItem["citations"],
    request_status: value.request_status ? String(value.request_status) : undefined,
    classification_reason: value.classification_reason ? String(value.classification_reason) : undefined,
    confidence_details: asRecord(value.confidence_details) as ReviewItem["confidence_details"],
    route_reason: value.route_reason ? String(value.route_reason) : undefined,
    decision_factors: asRecord(value.decision_factors) as ReviewItem["decision_factors"],
    escalation_reasons: (Array.isArray(value.escalation_reasons) ? value.escalation_reasons : [])
      .map((reason) => String(reason)),
    decision_started_at: value.decision_started_at === null || value.decision_started_at === undefined ? null : normalizeUtcTimestamp(value.decision_started_at),
    decision_error: value.decision_error === null || value.decision_error === undefined ? null : String(value.decision_error),
    decision_history: (Array.isArray(value.decision_history) ? value.decision_history : []).map((event) => asRecord(event)),
  };
}

function normalizeDocument(raw: unknown): KnowledgeDocument {
  const value = asRecord(raw);
  return {
    id: String(value.id ?? ""),
    title: String(value.title ?? "Untitled document"),
    filename: String(value.filename ?? ""),
    source: String(value.source ?? "Unknown source"),
    mime_type: String(value.mime_type ?? "application/octet-stream"),
    created_at: normalizeUtcTimestamp(value.created_at),
    chunk_count: asNumber(value.chunk_count),
    status: value.status ? String(value.status) : undefined,
    metadata: asRecord(value.metadata ?? value.metadata_json),
  };
}

function normalizeDocumentDetail(raw: unknown): KnowledgeDocumentDetail {
  const value = asRecord(raw);
  return {
    ...normalizeDocument(value),
    content: value.content === null || value.content === undefined ? undefined : String(value.content),
    chunks: (Array.isArray(value.chunks) ? value.chunks : []).map((entry) => {
      const chunk = asRecord(entry);
      return {
        id: String(chunk.id ?? ""),
        chunk_index: asNumber(chunk.chunk_index),
        page_number: chunk.page_number === null || chunk.page_number === undefined ? null : asNumber(chunk.page_number),
        content: String(chunk.content ?? ""),
        metadata: asRecord(chunk.metadata ?? chunk.metadata_json),
      };
    }),
    indexing: typeof value.indexing === "string" ? value.indexing : asRecord(value.indexing),
    content_offset: asNumber(value.content_offset),
    content_limit: asNumber(value.content_limit),
    content_total: asNumber(value.content_total, String(value.content ?? "").length),
    content_complete: value.content_complete === undefined ? true : Boolean(value.content_complete),
    next_content_offset: value.next_content_offset === null || value.next_content_offset === undefined ? null : asNumber(value.next_content_offset),
    chunk_offset: asNumber(value.chunk_offset),
    chunk_limit: asNumber(value.chunk_limit),
    chunk_total: asNumber(value.chunk_total, asNumber(value.chunk_count)),
    chunks_complete: value.chunks_complete === undefined ? true : Boolean(value.chunks_complete),
    next_chunk_offset: value.next_chunk_offset === null || value.next_chunk_offset === undefined ? null : asNumber(value.next_chunk_offset),
  };
}

function normalizeAvailableModel(raw: unknown): AvailableModel {
  const value = asRecord(raw);
  return {
    provider: String(value.provider ?? "unknown"),
    model: String(value.model ?? "unknown"),
    display_name: value.display_name ? String(value.display_name) : undefined,
    role: value.routing_description ? String(value.routing_description) : value.routing_role ? String(value.routing_role) : value.role ? String(value.role) : undefined,
    routing_role: value.routing_role ? String(value.routing_role) : undefined,
    description: value.routing_description ? String(value.routing_description) : value.description ? String(value.description) : undefined,
    quality: asNumber(value.quality_tier ?? value.quality ?? value.quality_score),
    input_cost_per_million: asNumber(value.input_usd_per_million ?? value.input_cost_per_million ?? value.input_cost_per_1m),
    output_cost_per_million: asNumber(value.output_usd_per_million ?? value.output_cost_per_million ?? value.output_cost_per_1m),
    capabilities: (Array.isArray(value.capabilities) ? value.capabilities : []).map((item) => String(item)),
    enabled: value.enabled === undefined ? true : Boolean(value.enabled),
    expected_latency_ms: asNumber(value.expected_latency_ms),
    max_context: asNumber(value.max_context),
    pricing_source: value.pricing_source ? String(value.pricing_source) : undefined,
    fallback_only: Boolean(value.fallback_only),
    availability: value.availability === "disabled" || value.availability === "local" || value.availability === "configured_unverified"
      ? value.availability
      : undefined,
  };
}

function normalizeMetrics(raw: unknown): MetricsSummary {
  const value = asRecord(raw);
  return {
    total_requests: asNumber(value.total_requests),
    success_rate: asNumber(value.success_rate),
    escalation_rate: asNumber(value.escalation_rate),
    average_latency_ms: asNumber(value.average_latency_ms),
    p95_latency_ms: asNumber(value.p95_latency_ms),
    total_tokens: asNumber(value.total_tokens),
    estimated_spend: asNumber(value.estimated_spend),
    error_rate: asNumber(value.error_rate),
    retrieval_hit_rate: asNumber(value.retrieval_hit_rate),
    pending_reviews: asNumber(value.pending_reviews),
    timeline: Array.isArray(value.timeline) ? value.timeline as MetricsSummary["timeline"] : [],
    recent_traces: Array.isArray(value.recent_traces) ? value.recent_traces.map((entry) => {
      const trace = asRecord(entry);
      return {
        trace_id: String(trace.trace_id ?? ""),
        status: String(trace.status ?? "unknown"),
        latency_ms: asNumber(trace.latency_ms),
        created_at: normalizeUtcTimestamp(trace.created_at),
      };
    }) : [],
  };
}

function normalizeModel(raw: unknown): ModelMetric {
  const value = asRecord(raw);
  return {
    provider: String(value.provider ?? "unknown"),
    model: String(value.model ?? "unknown"),
    requests: asNumber(value.requests ?? value.calls),
    tokens_in: asNumber(value.tokens_in ?? value.prompt_tokens),
    tokens_out: asNumber(value.tokens_out ?? value.completion_tokens),
    cost: asNumber(value.cost ?? value.estimated_spend),
    average_latency_ms: asNumber(value.average_latency_ms),
  };
}

function normalizeMetricSet(raw: unknown): EvaluationMetricSet {
  const value = asRecord(raw);
  return {
    pass_rate: asOptionalNumber(value.pass_rate),
    intent_accuracy: asOptionalNumber(value.intent_accuracy),
    retrieval_recall: asOptionalNumber(value.retrieval_recall),
    retrieval_hit_rate: asOptionalNumber(value.retrieval_hit_rate),
    citation_correctness: asOptionalNumber(value.citation_correctness),
    groundedness: asOptionalNumber(value.groundedness),
    escalation_correctness: asOptionalNumber(value.escalation_correctness ?? value.escalation_accuracy),
    structured_output_validity: asOptionalNumber(value.structured_output_validity),
    tool_policy_accuracy: asOptionalNumber(value.tool_policy_accuracy),
    p95_latency_ms: asOptionalNumber(value.p95_latency_ms ?? value.average_latency_ms),
    estimated_cost: asOptionalNumber(value.estimated_cost),
    failure_rate: asOptionalNumber(value.failure_rate),
  };
}

function normalizeEvaluationRun(raw: unknown): EvaluationRun {
  const value = asRecord(raw);
  const summary = asRecord(value.summary);
  const rawConfigurations = asRecord(summary.configurations);
  const configurationMetrics = Object.fromEntries(
    Object.entries(rawConfigurations).map(([name, metrics]) => [name, normalizeMetricSet(metrics)]),
  );
  const preferred = configurationMetrics.improved ?? configurationMetrics.baseline;
  const rawResults = Array.isArray(value.results) ? value.results : [];
  return {
    id: String(value.id ?? ""),
    name: String(value.name ?? "Evaluation run"),
    status: value.status ? String(value.status) : undefined,
    started_at: normalizeUtcTimestamp(value.started_at),
    completed_at: value.completed_at === null || value.completed_at === undefined ? null : normalizeUtcTimestamp(value.completed_at),
    config: asRecord(value.config),
    metrics: preferred,
    configuration_metrics: configurationMetrics,
    provenance_valid: asOptionalBoolean(summary.provenance_valid),
    invalid_reason: summary.invalid_reason ? String(summary.invalid_reason) : undefined,
    results: rawResults.map((entry) => {
      const result = asRecord(entry);
      const caseId = String(result.case_id ?? "unknown");
      const details = asRecord(result.details);
      return {
        id: String(result.id ?? caseId),
        case_id: caseId,
        model: result.model ? String(result.model) : undefined,
        configuration: result.configuration ? String(result.configuration) : undefined,
        category: details.category ? String(details.category) : caseId.split("-")[0] ?? "unknown",
        passed: Boolean(result.passed),
        correctness_score: asOptionalNumber(result.correctness_score),
        groundedness_score: asOptionalNumber(result.groundedness_score),
        retrieval_score: asOptionalNumber(result.retrieval_score),
        latency_ms: asNumber(result.latency_ms),
        estimated_cost: asOptionalNumber(result.estimated_cost),
        details,
        intent_correct: asOptionalBoolean(result.intent_correct),
        escalation_correct: asOptionalBoolean(result.escalation_correct),
        citation_correctness_score: asOptionalNumber(result.citation_correctness_score),
        structured_output_valid: asOptionalBoolean(result.structured_output_valid),
      };
    }),
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
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
    const envelope = asRecord(details);
    const detail = envelope.detail;
    const structuredDetail = asRecord(detail);
    const message = typeof detail === "string"
      ? detail
      : Object.keys(structuredDetail).length
        ? [
            structuredDetail.message ? String(structuredDetail.message) : `Request failed with status ${response.status}`,
            structuredDetail.evaluation_run_id ? `Evaluation ${String(structuredDetail.evaluation_run_id)} is still running.` : "",
            structuredDetail.poll_url ? `Progress: ${String(structuredDetail.poll_url)}` : "",
          ].filter(Boolean).join(" ")
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, details);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function unwrapList<T>(payload: T[] | { items: T[] }): T[] {
  return Array.isArray(payload) ? payload : payload.items;
}

export const client = {
  createRequest(input: {
    message: string;
    user_id: string | null;
    channel: Channel;
    metadata: Record<string, unknown>;
    routing_strategy?: RoutingStrategy;
    explicit_model?: string;
  }) {
    return api<unknown>("/requests", {
      method: "POST",
      body: JSON.stringify(input),
    }).then(normalizeRequest);
  },

  getRequest(id: string) {
    return api<unknown>(`/requests/${encodeURIComponent(id)}`).then(normalizeRequest);
  },

  async getReviews(status: string | null = null) {
    const query = status ? `?status=${encodeURIComponent(status)}` : "?status=";
    return unwrapList(await api<unknown[] | { items: unknown[] }>(`/reviews${query}`)).map(normalizeReview);
  },

  reviewAction(
    id: string,
    action: "approve" | "reject" | "edit-and-approve",
    payload: { reviewer_notes?: string; edited_response?: string } = {},
  ) {
    return api<unknown>(`/reviews/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }).then(normalizeReview);
  },

  async getDocuments(options: { limit?: number; offset?: number; search?: string; source?: string } = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options)) {
      if (value !== undefined && value !== "") query.set(key, String(value));
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    return unwrapList(
      await api<unknown[] | { items: unknown[] }>(`/knowledge/documents${suffix}`),
    ).map(normalizeDocument);
  },

  getDocument(id: string, options: { content_offset?: number; content_limit?: number; chunk_offset?: number; chunk_limit?: number } = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options)) {
      if (value !== undefined) query.set(key, String(value));
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    return api<unknown>(`/knowledge/documents/${encodeURIComponent(id)}${suffix}`).then(normalizeDocumentDetail);
  },

  uploadDocument(file: File, title: string, source: string, documentType: "auto" | "general" | "invoice") {
    const body = new FormData();
    body.append("file", file);
    body.append("title", title);
    body.append("source", source);
    body.append("document_type", documentType);
    return api<KnowledgeDocument>("/knowledge/documents", { method: "POST", body })
      .then((document) => ({ ...document, created_at: normalizeUtcTimestamp(document.created_at) }));
  },

  deleteDocument(id: string) {
    return api<void>(`/knowledge/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  runEvaluation(config: Record<string, unknown> = { configuration: "comparison" }) {
    return api<unknown>("/evals/run", {
      method: "POST",
      body: JSON.stringify(config),
    }).then(normalizeEvaluationRun);
  },

  async getEvaluationRuns() {
    return unwrapList(await api<unknown[] | { items: unknown[] }>("/evals/runs")).map(normalizeEvaluationRun);
  },

  getEvaluationRun(id: string) {
    return api<unknown>(`/evals/runs/${encodeURIComponent(id)}`).then(normalizeEvaluationRun);
  },

  getMetrics() {
    return api<unknown>("/metrics/summary").then(normalizeMetrics);
  },

  async getModelMetrics() {
    return unwrapList(await api<unknown[] | { items: unknown[] }>("/metrics/models")).map(normalizeModel);
  },

  async getModels() {
    return unwrapList(await api<unknown[] | { items: unknown[] }>("/models")).map(normalizeAvailableModel);
  },
};
