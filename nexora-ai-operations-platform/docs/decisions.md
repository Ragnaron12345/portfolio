# Architecture Decisions and Trade-offs

This log records decisions that shape Nexora AI Operations Platform. “Accepted” means the design is authoritative for implementation; it does not by itself prove that the behavior is complete. Material deviations require a new entry or an explicit superseding decision.

## ADR-001 — Modular monolith before distributed services

- **Status:** Accepted
- **Decision:** Keep request orchestration, RAG, routing, tools, review, observability, and evaluation in one FastAPI deployable with internal module boundaries.
- **Why:** A single process and database make the portfolio demo reproducible, preserve end-to-end traces, and avoid distributed failure modes that do not improve the core signal.
- **Trade-off:** Components cannot scale or deploy independently. Long-running ingestion/evaluation may later need workers, but their service interfaces and persisted state can be extracted without changing HTTP contracts.
- **Rejected for now:** Microservices and an event bus; they add operational surface without a demonstrated load requirement.

## ADR-002 — PostgreSQL plus pgvector as the system of record

- **Status:** Accepted
- **Decision:** Store workflow records, document metadata/chunks, evaluation data, and vectors in PostgreSQL with pgvector.
- **Why:** Transactions keep document visibility and review/audit state coherent, while one local Docker dependency makes the demo easier to run.
- **Trade-off:** A dedicated vector database could provide richer large-scale indexing, but would introduce synchronization, backup, and consistency concerns. The chosen design is appropriate for the demo corpus, not a universal scale claim.

## ADR-003 — Provider and embedding adapters

- **Status:** Accepted
- **Decision:** Normalize model generation and embedding behind internal interfaces; implement OpenAI, AI Prime Tech's OpenAI-compatible Chat Completions endpoint, and deterministic local/mock paths. AI Prime Tech has a separate credential and does not receive OpenAI credentials.
- **Why:** Routing, fallback, tests, and stored usage should not depend on one SDK response shape.
- **Trade-off:** A common interface exposes only deliberately shared capabilities and requires adapter maintenance. Provider-specific features may need capability tags or optional extensions rather than leaking SDK objects inward.

## ADR-004 — Deterministic-first classification

- **Status:** Accepted
- **Decision:** Use explicit rules for obvious security, high-risk, and tool patterns, then use an LLM structured-output classifier for genuinely ambiguous input.
- **Why:** Safety-critical outcomes become testable and cheap while the LLM handles linguistic variation.
- **Trade-off:** Rules can become brittle or overlap. They must stay small, ordered, observable, and covered by regression cases; they are not a substitute for evaluation.

## ADR-005 — Model routing is policy, not model discretion

- **Status:** Accepted
- **Decision:** Select from an enabled registry using `cheapest_adequate`, `quality_first`, `latency_first`, explicit-model, or bounded fallback strategies. Fable handles fast/simple work, Sonnet routine grounded policy, and Opus high-risk/conflict/complex work. A risk/complexity quality floor may safely override an explicitly requested weaker model. Persist all factors, route reason, attempts, tokens, and configured cost estimates.
- **Why:** Cost, latency, capability, and provider failure are application concerns.
- **Trade-off:** Registry costs and capabilities can become stale. Configuration needs versioning, validation, and periodic review; an estimated cost is not an invoice.

## ADR-006 — Confidence is a workflow decision score

- **Status:** Accepted
- **Decision:** Combine retrieval evidence, citations, structured validity, tool success, answer validation, and self-check signals into a documented decision heuristic.
- **Why:** A single model-generated “confidence” number is not a calibrated probability and should not authorize an action.
- **Trade-off:** Thresholds remain policy choices and can be miscalibrated. Store component scores, evaluate escalation precision/recall, and call the value a heuristic in API/UI copy.

## ADR-007 — Retrieved content and tool output are untrusted data

- **Status:** Accepted
- **Decision:** Delimit external content, never place it in an instruction role, and prohibit it from expanding tool authority or changing security policy.
- **Why:** Direct and indirect prompt injection are expected operating conditions, not exceptional input.
- **Trade-off:** Strong separation can reduce usefulness when a document legitimately describes a workflow. The application must translate approved policy into code/configuration; it cannot execute prose.

## ADR-008 — Three schema-validated demo tools only

- **Status:** Accepted
- **Decision:** Allow only `get_customer_summary`, `create_support_ticket`, and `get_service_status`, each with Pydantic arguments, normalized results, authorization checks, and audit records.
- **Why:** This demonstrates tool calling while keeping side effects and failure behavior understandable.
- **Trade-off:** The tool surface is intentionally narrow and cannot complete every customer request. Unsupported actions must be stated and reviewed instead of simulated. No shell, arbitrary SQL, or unrestricted HTTP executor will be added.

## ADR-009 — Human review is an explicit terminal workflow state

- **Status:** Accepted
- **Decision:** Persist original request/answer, citations, reason, score components, model, timestamps, and reviewer decision. High risk, weak evidence, conflicts, invalid structure, and required-tool failure enter review.
- **Why:** Review must be auditable and visible, not a vague sentence appended to an otherwise completed response.
- **Trade-off:** Conservative escalation increases reviewer load and latency. Evaluation must measure both missed escalations and unnecessary escalations before thresholds change.

## ADR-010 — Synthetic corpus contains controlled contradictions

- **Status:** Accepted
- **Decision:** Use six fictional fintech documents with five explicit current-source conflicts and known information gaps.
- **Why:** A uniformly consistent corpus cannot demonstrate whether the system detects contradictions or admits that evidence is missing.
- **Trade-off:** Retrieval may surface conflicts for nearby factual questions, lowering simple keyword scores. Evaluation therefore uses case-specific expected sources and treats conflict handling as a first-class safety outcome.

## ADR-011 — Compare retrieval configurations with a fixed answer budget

- **Status:** Accepted
- **Decision:** Compare a fixed-chunk dense baseline with an improved combined pipeline that adds keyword fusion, domain query expansion, and opportunistic retrieval while keeping the persisted chunks, Top-K response budget, routing policy, and provider constraints fixed.
- **Why:** The comparison measures whether the practical retrieval/orchestration bundle improves the visible regression suite.
- **Trade-off:** This is a multi-variable experiment, not an isolated reranker or chunking ablation. Its delta must not be attributed to a single retrieval technique.

## ADR-012 — Benchmark tables come only from persisted runs

- **Status:** Accepted
- **Decision:** Generate comparison values from stored evaluation records and publish a versioned artifact that pins run identity, timestamps, evaluated inputs, core runtime hashes, environment facts, summary metrics, and compact per-case evidence.
- **Why:** Hand-entered portfolio numbers are not reproducible evidence and the project explicitly forbids fabricated benchmarks.
- **Trade-off:** A local deterministic artifact is reproducible regression evidence, not a production or provider benchmark; provider-backed runs must be labeled separately and use repeated trials.

## ADR-013 — Redis is optional, not a core dependency

- **Status:** Accepted
- **Decision:** The required local path runs with frontend, backend, and PostgreSQL/pgvector. Redis may later support distributed rate limiting, caching, or workers.
- **Why:** Avoiding an unnecessary dependency improves first-run reliability.
- **Trade-off:** In-process limiting/caching does not coordinate across multiple backend replicas. A production multi-replica deployment must add a shared implementation or gateway control.

## ADR-014 — Synchronous request contract, asynchronous-friendly internals

- **Status:** Accepted
- **Decision:** Keep the primary request API understandable as a synchronous workflow for the demo, with bounded timeouts and persisted intermediate records. Evaluation starts use a persisted work fingerprint and return the existing running job on an identical retry, so a proxy timeout cannot silently duplicate paid provider work. Design ingestion/evaluation state so background workers can be introduced later.
- **Why:** The portfolio needs a working end-to-end interaction more than a queueing platform.
- **Trade-off:** Slow providers can approach HTTP timeout limits. A retry can recover the existing run ID and poll it, but the current single-process guard is not a distributed queue or lease; multi-worker deployment requires a database-backed job claim. Streaming or a durable worker may improve UX later, but cannot weaken audit, cancellation, or terminal-state semantics.

## ADR-015 — Security failures fail closed with safe observability

- **Status:** Accepted
- **Decision:** Reject invalid uploads/tool arguments/structured outputs, bound retries and tokens, redact logs, use explicit CORS and security headers, and create review/error outcomes rather than speculative answers.
- **Why:** Availability and fluent responses are secondary to preventing unauthorized actions or leakage.
- **Trade-off:** Fail-closed behavior can create false rejections and reviewer load. Record safe error categories and use tests/evals to refine controls without exposing raw secrets or provider payloads.
