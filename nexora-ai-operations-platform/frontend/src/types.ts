export type Channel = "web" | "email" | "slack" | "api";
export type RiskLevel = "low" | "medium" | "high";
export type RoutingStrategy = "cheapest_adequate" | "quality_first" | "latency_first" | "explicit_model" | "fallback_chain";

export interface Citation {
  document_id?: string;
  chunk_id?: string;
  title: string;
  source: string;
  page_number?: number | null;
  chunk_index?: number;
  score?: number;
  excerpt?: string;
}

export interface ToolCall {
  id?: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  status: string;
  latency_ms?: number;
  requires_approval?: boolean;
  error?: string | null;
}

export interface ProviderAttempt {
  id?: string;
  provider: string;
  model: string;
  purpose?: string;
  route_reason?: string | null;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_ms?: number;
  estimated_cost?: number;
  retries?: number;
  success: boolean;
  error?: string | null;
  created_at?: string;
}

export interface RequestResult {
  request_id: string;
  trace_id?: string;
  status: string;
  response: string | null;
  citations: Citation[];
  confidence: number;
  model_used: string | null;
  requires_review: boolean;
  topic?: string;
  topic_reason?: string;
  intent?: string;
  risk_level?: RiskLevel;
  risk_reason?: string;
  risk_factors?: string[];
  classification_reason?: string;
  needs_retrieval?: boolean;
  needs_tools?: boolean;
  route_reason?: string;
  latency_ms?: number;
  estimated_cost?: number;
  tokens_in?: number;
  tokens_out?: number;
  tool_calls?: ToolCall[];
  confidence_details?: Record<string, unknown>;
  decision_factors?: Record<string, unknown>;
  provider_attempts?: ProviderAttempt[];
  escalation_reasons?: string[];
  stage_timings?: Record<string, number>;
  created_at?: string;
  completed_at?: string | null;
  channel?: Channel;
  message?: string;
}

export interface MetricsSummary {
  total_requests: number;
  success_rate: number;
  escalation_rate: number;
  average_latency_ms: number;
  p95_latency_ms: number;
  total_tokens: number;
  estimated_spend: number;
  error_rate: number;
  retrieval_hit_rate: number;
  pending_reviews: number;
  timeline?: Array<{
    bucket: string;
    requests: number;
    latency_ms: number;
  }>;
  recent_traces?: Array<{
    trace_id: string;
    status: string;
    latency_ms: number;
    created_at: string;
  }>;
}

export interface ModelMetric {
  provider: string;
  model: string;
  requests: number;
  percentage?: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  average_latency_ms: number;
}

export interface AvailableModel {
  provider: string;
  model: string;
  display_name?: string;
  role?: string;
  routing_role?: string;
  description?: string;
  quality?: number;
  input_cost_per_million?: number;
  output_cost_per_million?: number;
  capabilities?: string[];
  enabled?: boolean;
  expected_latency_ms?: number;
  max_context?: number;
  pricing_source?: string;
  fallback_only?: boolean;
  availability?: "disabled" | "local" | "configured_unverified";
}

export interface ReviewItem {
  id: string;
  request_id: string;
  reason: string;
  status: string;
  reviewer_notes?: string | null;
  edited_response?: string | null;
  created_at: string;
  resolved_at?: string | null;
  request?: RequestResult & { message?: string };
  message?: string;
  response?: string;
  confidence?: number;
  risk_level?: RiskLevel;
  model?: string;
  topic?: string;
  topic_reason?: string;
  intent?: string;
  risk_reason?: string;
  risk_factors?: string[];
  citations?: Citation[];
  request_status?: string;
  classification_reason?: string;
  confidence_details?: Record<string, unknown>;
  route_reason?: string;
  decision_factors?: Record<string, unknown>;
  escalation_reasons?: string[];
  decision_started_at?: string | null;
  decision_error?: string | null;
  decision_history?: Array<Record<string, unknown>>;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  filename: string;
  source: string;
  mime_type: string;
  created_at: string;
  chunk_count?: number;
  status?: string;
  metadata?: Record<string, unknown>;
}

export type DocumentType = "auto" | "general" | "invoice";

export interface KnowledgeChunk {
  id: string;
  chunk_index: number;
  page_number?: number | null;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  content?: string;
  chunks: KnowledgeChunk[];
  indexing?: Record<string, unknown> | string;
  content_offset?: number;
  content_limit?: number;
  content_total?: number;
  content_complete?: boolean;
  next_content_offset?: number | null;
  chunk_offset?: number;
  chunk_limit?: number;
  chunk_total?: number;
  chunks_complete?: boolean;
  next_chunk_offset?: number | null;
}

export interface EvaluationMetricSet {
  pass_rate?: number;
  intent_accuracy?: number;
  retrieval_recall?: number;
  retrieval_hit_rate?: number;
  citation_correctness?: number;
  groundedness?: number;
  escalation_correctness?: number;
  structured_output_validity?: number;
  tool_policy_accuracy?: number;
  p95_latency_ms?: number;
  estimated_cost?: number;
  failure_rate?: number;
}

export interface EvaluationResult {
  id: string;
  case_id: string;
  model?: string;
  configuration?: string;
  category?: string;
  passed: boolean;
  correctness_score?: number;
  groundedness_score?: number;
  retrieval_score?: number;
  latency_ms: number;
  estimated_cost?: number;
  details?: Record<string, unknown>;
  intent_correct?: boolean;
  escalation_correct?: boolean;
  citation_correctness_score?: number;
  structured_output_valid?: boolean;
}

export interface EvaluationRun {
  id: string;
  name: string;
  status?: string;
  started_at: string;
  completed_at?: string | null;
  config?: Record<string, unknown>;
  metrics?: EvaluationMetricSet;
  configuration_metrics?: Record<string, EvaluationMetricSet>;
  results?: EvaluationResult[];
  provenance_valid?: boolean;
  invalid_reason?: string;
}
