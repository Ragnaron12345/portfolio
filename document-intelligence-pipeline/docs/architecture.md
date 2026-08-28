# Architecture

DocIntel separates trust boundaries: upload bytes, extracted document data,
provider output, deterministic rules, workflow decisions, and reviewer actions
are persisted as distinct evidence.

## Processing lifecycle

1. Stream the upload into a bounded temporary file while computing SHA-256.
2. Validate extension, declared MIME, content signature, byte limit, pages, and decoded image pixels.
3. Read native PDF text page-by-page with PyMuPDF; OCR only low-density pages. Images always use OCR.
4. Classify into invoice, bank statement, customer application, or unknown with a reason and confidence.
5. Extract against a strict Pydantic schema. Remote output receives one safe repair attempt.
6. Run document-specific deterministic rules.
7. Calculate the stored confidence breakdown from named, weighted components.
8. Auto-accept or create a pending review item with the exact reason.
9. Persist every stage, duration, provider/model, retry, error, and decision.

The default deterministic provider is deliberately useful and testable offline.
`openai` mode sends extracted text—not original pixels—to an OpenAI-compatible
Chat Completions endpoint with strict JSON Schema. A failed provider call can
fall back to deterministic extraction in development/auto flows.

## Persistence

SQLAlchemy 2.x models are portable between PostgreSQL 16 in Docker Compose and
SQLite in tests. Original files live under the configured storage directory;
the database stores an opaque safe filename, checksum, MIME, byte size, and
absolute runtime path.

The local demo is synchronous by design so every acceptance path is observable.
A public deployment should put processing behind a durable queue and immutable
object storage while preserving the same stage contract.

## Frontend state

React surfaces list loading, empty, error, and populated states. Document and
review selections survive refresh operations as long as the item remains in the
result set. Evaluation selection stores only the selected run ID under the
versioned key `docintel:selected-evaluation:v1`; no document data or PII enters
browser storage.
