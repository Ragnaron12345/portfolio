export type StageStatus = "pending" | "running" | "success" | "warning" | "failed" | "skipped"

export interface Stage {
  name: string
  status: StageStatus
  duration_ms: number
  summary: string
  error: string | null
}

export interface PageExtraction {
  page_number: number
  extraction_method: "native" | "ocr"
  text: string
  character_count: number
  ocr_quality: number | null
  latency_ms: number
}

export interface ValidationRule {
  rule_id: string
  name: string
  status: "pass" | "warning" | "fail" | "not_applicable"
  message: string
  details: Record<string, unknown>
}

export interface DocumentSummary {
  id: string
  trace_id: string
  filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  status: string
  document_type: string
  classification: { document_type: string; confidence: number; reason: string }
  confidence: number
  review_reason: string | null
  provider: string
  model: string
  retries: number
  total_latency_ms: number
  error: string | null
  created_at: string
  completed_at: string | null
}

export interface DocumentDetail extends DocumentSummary {
  stages: Stage[]
  pages: PageExtraction[]
  structured_data: Record<string, unknown> | null
  validation: ValidationRule[]
  confidence_breakdown: {
    definition?: string
    components?: Record<string, number>
    weights?: Record<string, number>
  }
}

export interface ReviewSummary {
  id: string
  document_id: string
  filename: string
  document_type: string
  confidence: number
  reason: string
  status: string
  created_at: string
  resolved_at: string | null
}

export interface ReviewDetail extends ReviewSummary {
  document: DocumentDetail
  decision_history: Array<Record<string, string | null>>
  reviewer_notes: string | null
  edited_fields: Record<string, unknown> | null
}

export interface MetricValue {
  value: number
  unit: string
  definition: string
}

export interface Metrics {
  documents_processed: MetricValue
  auto_accept_rate: MetricValue
  review_rate: MetricValue
  failed_processing_rate: MetricValue
  average_latency: MetricValue
  p95_latency: MetricValue
  document_type_distribution: Record<string, number>
  common_validation_failures: Array<{ name: string; count: number }>
  recent_activity: DocumentSummary[]
}

export interface EvaluationSummary {
  id: string
  name: string
  status: string
  dataset_size: number
  started_at: string
  completed_at: string | null
}

export interface EvaluationMetric {
  key: string
  label: string
  definition: string
  unit: string
  higher_is_better: boolean
  baseline: number
  improved: number
  delta: number
  improvement: number
}

export interface EvaluationDetail extends EvaluationSummary {
  config: { baseline: string; improved: string; dataset_sha256: string; dataset: string }
  metrics: EvaluationMetric[]
  details: {
    document_counts: Record<string, number>
    most_improved: Array<Record<string, string>>
    remaining_failures: Array<Record<string, string>>
    methodology: string
  }
}
