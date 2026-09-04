export type WorkflowKey = "support" | "invoice" | "incident";

export type ExecutionStatus =
  | "received"
  | "running"
  | "waiting_for_review"
  | "completed"
  | "completed_with_warning"
  | "failed"
  | "cancelled"
  | string;

export type StageState = "completed" | "running" | "waiting" | "failed" | "pending" | string;

export interface Classification {
  category: string;
  risk_level: string;
  confidence: number;
  reason: string;
  needs_human: boolean;
  confidence_basis: string[];
}

export interface SourceEvidence {
  id: string;
  title: string;
  excerpt: string;
  relevance: number;
}

export interface ValidationResult {
  rule: string;
  passed: boolean;
  message: string;
  expected?: string;
  actual?: string;
}

export interface ExtractedField {
  name: string;
  value: string;
  confidence?: number;
}

export interface IncidentSummary {
  title: string;
  observed_symptoms: string[];
  probable_impact: string;
  possible_causes: string[];
  suggested_investigation_steps: string[];
  confidence: number;
}

export interface ExternalAction {
  system: string;
  action: string;
  status: string;
  reference?: string;
  message?: string;
}

export interface ExecutionEvent {
  id: string;
  stage: string;
  label: string;
  status: StageState;
  occurred_at?: string;
  completed_at?: string;
  duration_ms?: number;
  message?: string;
  retry?: number;
}

export interface Execution {
  execution_id: string;
  correlation_id: string;
  workflow: string;
  workflow_key: WorkflowKey;
  current_stage: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  decision_summary: string;
  decision_reason: string;
  retry_count: number;
  ai_attempt_count: number | null;
  input: Record<string, unknown>;
  classification?: Classification;
  sources: SourceEvidence[];
  generated_draft?: string;
  extracted_fields: ExtractedField[];
  validations: ValidationResult[];
  original_file?: string;
  incident_summary?: IncidentSummary;
  deduplicated_into?: string;
  external_actions: ExternalAction[];
  events: ExecutionEvent[];
}

export interface WorkflowMetric {
  workflow: string;
  workflow_key: WorkflowKey;
  executions: number;
  success_rate: number;
  review_rate: number;
  failure_rate: number;
  average_latency_ms: number;
  p95_latency_ms?: number;
  status: "healthy" | "degraded" | "unhealthy" | string;
  trend: number[];
}

export interface Metrics {
  executions_today: number;
  success_rate: number;
  failure_rate: number;
  review_rate: number;
  average_latency_ms: number;
  p95_latency_ms: number;
  pending_reviews: number;
  workflows: WorkflowMetric[];
}

export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy" | string;
  label: string;
  checked_at: string;
}

export interface ReviewDecision {
  decision: string;
  reviewer: string;
  note: string;
  created_at: string;
}

export interface Approval {
  id: string;
  workflow: string;
  execution_id: string;
  title: string;
  reason: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  reviewer_note: string;
  decision_context: Record<string, unknown>;
  execution?: Execution;
  history: ReviewDecision[];
}

export interface AuditEvent {
  id: string;
  execution_id: string;
  correlation_id: string;
  workflow: string;
  event_type: string;
  actor: string;
  action: string;
  outcome: string;
  reason: string;
  created_at: string;
}

export type MockSystemKey = "tickets" | "incidents" | "messages" | "invoices";

export interface MockRecord {
  id: string;
  execution_id: string;
  title: string;
  status: string;
  created_at: string;
  fields: Array<{ label: string; value: string }>;
}

export interface DemoScenario {
  id: string;
  workflow: WorkflowKey;
  name: string;
  description: string;
  outcome: string;
  risk?: string;
}

export interface ListResponse<T> {
  items: T[];
  total: number;
}
