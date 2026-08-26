# Architecture

Nexora is a portfolio-scale AI operations platform with a React operator UI,
FastAPI backend, PostgreSQL/pgvector persistence, and deterministic offline
providers. Docker Compose runs the complete local stack.

## Request lifecycle

1. Validate the request and classify intent, topic, and risk.
2. Retrieve relevant knowledge through semantic or hybrid ranking.
3. Select the cheapest adequate model under the configured routing strategy.
4. Execute only allowlisted tools with schema-validated arguments.
5. Generate and validate a grounded structured response.
6. Return automatically or create a Review Queue item.
7. Persist traces, provider attempts, cost, latency, citations, and decisions.

Remote models are optional. Mock mode makes development and CI deterministic;
OpenAI-compatible endpoints are runtime configuration.

## Document AI vertical slice

Knowledge ingestion supports Markdown, text, native-text PDF, scanned PDF, PNG,
and JPEG. Native PDF text is preferred. When no PDF text exists, or when an
image is uploaded, the backend renders pages and performs local Tesseract OCR.

The deliberately narrow first workflow is invoice extraction:

```text
scan/image -> OCR -> invoice entities -> validation -> confidence -> review/index
```

Extracted entities are invoice number, date, currency, and total. Missing or
invalid required fields and confidence below 0.85 create a pending item in the
same Review Queue used by request workflows. OCR text and structured processing
metadata remain attached to the indexed document for auditability.

This slice demonstrates the control plane, not a claim of universal OCR or
document classification. Production extensions should add language packs,
layout-aware models, document-type routing, immutable source storage, and
field-level reviewer corrections.

## Main boundaries

- `backend/app/services/ai`: classification, routing, providers, orchestration.
- `backend/app/services/rag`: parsing, OCR, chunking, embeddings, retrieval.
- `backend/app/services/evaluation`: regression and held-out evaluation runner.
- `backend/app/services/tools`: allowlisted operational tools.
- `backend/app/services/review_service.py`: reviewer state transitions.
- `frontend/src/pages`: Overview, Console, Review, Knowledge, Evaluations.

SQLite-backed tests exercise the same ORM models used with PostgreSQL. Vector
spaces are never mixed: explicit remote embedding mode indexes and queries with
the same provider, while auto/mock modes use stable local hash embeddings.

## Operational limits

The bundled deployment is single-process and intended for local demonstration.
Upload byte, decoded-text, page, chunk, metadata, and request limits are enforced.
Evaluation snapshots prevent concurrent knowledge mutation. A production
deployment would replace in-process locks with durable leases and object storage.


