export type RunStatus = "queued" | "running" | "completed" | "completed_with_errors" | "failed" | "cancelled";

export interface Dataset {
  id: string;
  name: string;
  version: string;
  content_hash: string;
  case_count: number;
  cases: DatasetCase[] | null;
  created_at: string;
}

export interface DatasetCase {
  id: string;
  input: string;
  reference_answer: string | null;
  expected_keywords: string[];
  forbidden_claims: string[];
  context: string[];
  expected_citations: string[];
  metadata: Record<string, unknown>;
}

export interface ModelConfig {
  id: string;
  name: string;
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  retries: number;
  input_price_per_million: number | null;
  output_price_per_million: number | null;
  pricing_source: string | null;
}

export interface PromptVersion {
  id: string;
  name: string;
  semantic_version: string;
  system_prompt: string;
  user_template: string;
  tags: string[];
  created_at: string;
}

export interface RetrievalConfig {
  id: string;
  name: string;
  chunk_size: number;
  overlap: number;
  top_k: number;
  reranker_enabled: boolean;
  embedding_model: string;
  mode: string;
}

export interface Combination {
  key: string;
  label: string;
  model_config_id: string;
  prompt_version_id: string;
  retrieval_config_id: string;
}

export interface ConfigSnapshot {
  dataset: Dataset & { hash: string; cases: DatasetCase[] };
  models: ModelConfig[];
  prompts: PromptVersion[];
  retrieval_configs: RetrievalConfig[];
  evaluator_config: Record<string, unknown>;
  git_commit: string | null;
  timestamp: string;
  combinations: Combination[];
}

export interface RunSummary {
  id: string;
  experiment_id: string;
  experiment_name: string;
  status: RunStatus;
  total: number;
  completed: number;
  successful: number;
  failed: number;
  retried: number;
  progress_percent: number;
  elapsed_seconds: number | null;
  eta_seconds: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  total_cost_usd: number | null;
  average_cost_per_successful_case_usd: number | null;
  config_snapshot: ConfigSnapshot;
  git_commit: string | null;
  recovery_note: string | null;
}

export interface OverviewData {
  runs_this_week: number;
  success_rate: number | null;
  success_numerator: number;
  success_denominator: number;
  average_p95_latency_ms: number | null;
  total_spend_usd: number | null;
  datasets_registered: number;
  models_registered: number;
  recent_runs: RunSummary[];
  regression_watch: FailureCase[];
  regression_run_id: string | null;
}

export interface MetricValue {
  name: string;
  label: string;
  value: number | null;
  unit: string;
  definition: string;
  better_direction: "higher" | "lower";
  sample_count: number;
  metric_type: "deterministic" | "judge";
  numerator: number | null;
  denominator: number | null;
}

export interface ComparisonMetric {
  name: string;
  label: string;
  unit: string;
  definition: string;
  better_direction: "higher" | "lower";
  metric_type: "deterministic" | "judge";
  baseline: MetricValue | null;
  candidate: MetricValue | null;
  delta: {
    absolute: number | null;
    relative_percent: number | null;
    improved: boolean | null;
    display_unit: string;
  };
}

export interface ExactConfiguration {
  combination: Combination;
  model: ModelConfig;
  prompt: PromptVersion;
  retrieval: RetrievalConfig;
  evaluator_config: Record<string, unknown>;
  dataset: Record<string, unknown>;
  git_commit: string | null;
  timestamp: string;
}

export interface ComparisonData {
  run_id: string;
  baseline: { key: string; label: string; configuration: ExactConfiguration };
  candidate: { key: string; label: string; configuration: ExactConfiguration };
  metrics: ComparisonMetric[];
  all_configurations: Array<{ key: string; label: string; configuration: ExactConfiguration; metrics: MetricValue[] }>;
}

export interface RetrievedChunk {
  rank: number;
  score: number;
  source_id: string;
  text: string;
  expected_source: boolean;
}

export interface FailureCase {
  id: string;
  case_id: string;
  combination_key: string;
  model_config_id: string;
  prompt_version_id: string;
  retrieval_config_id: string;
  category: string;
  input: string;
  reference_answer: string | null;
  context: string[];
  output: string | null;
  status: string;
  error_type: string | null;
  error_message: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  retry_count: number;
  retrieved_chunks: RetrievedChunk[];
  failed_metrics: string[];
  metrics: MetricValue[];
  judge: Record<string, unknown> | null;
  classification: "improved" | "unchanged" | "regressed" | null;
}

export interface FailureData {
  run_id: string;
  items: FailureCase[];
  total: number;
  pairwise_counts: { improved: number; unchanged: number; regressed: number };
}
