# API Reference

## Base URLs

| Environment | Base |
| --- | --- |
| Browser / Compose | `http://localhost:3000/api/v1` |
| Direct backend | `http://localhost:8001/api/v1` |
| Interactive OpenAPI | `http://localhost:3000/api/v1/docs` |
| OpenAPI JSON | `http://localhost:3000/api/v1/openapi.json` |

The OpenAPI contract is authoritative as the implementation evolves. JSON endpoints use UTF-8. Upload uses `multipart/form-data`.

## Endpoint index

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/requests` | Process and persist one AI request. |
| GET | `/requests/{request_id}` | Retrieve the complete request trace result. |
| GET | `/reviews` | List operational review items. |
| POST | `/reviews/{review_id}/approve` | Approve the generated response. |
| POST | `/reviews/{review_id}/reject` | Reject the response. |
| POST | `/reviews/{review_id}/edit-and-approve` | Store and approve an edited response. |
| POST | `/knowledge/documents` | Validate, ingest, embed, and index a document. |
| GET | `/knowledge/documents` | List/search/filter documents. |
| GET | `/knowledge/documents/{document_id}` | Read bounded document text and chunks. |
| DELETE | `/knowledge/documents/{document_id}` | Delete a document and its chunks. |
| POST | `/evals/run` | Run a persisted evaluation comparison. |
| GET | `/evals/runs` | List immutable evaluation snapshots. |
| GET | `/evals/runs/{run_id}` | Read one run and all case results. |
| GET | `/metrics/summary` | Read aggregate operational metrics. |
| GET | `/metrics/models` | Read per-model usage metrics. |
| GET | `/models` | Read non-secret configured model capabilities. |
| GET | `/health` | Read local/database/provider-configuration health. |

## Requests

### POST `/requests`

```json
{
  "message": "Customer CUST-1002 says their card is stolen. What should we do?",
  "user_id": "CUST-1002",
  "channel": "web",
  "metadata": { "scenario": "portfolio-demo" },
  "routing_strategy": "cheapest_adequate",
  "explicit_model": null
}
```

Constraints:

- `message`: 1–12,000 characters, non-blank, no null byte;
- `user_id`: optional, maximum 200 characters;
- `channel`: `web`, `email`, `slack`, or `api`;
- `routing_strategy`: `cheapest_adequate`, `quality_first`, `latency_first`, `explicit_model`, or `fallback_chain`;
- `explicit_model` is required and must be enabled when strategy is `explicit_model`;
- metadata is bounded by configured serialized-byte limits.

Success returns `201 Created` and the complete `RequestRead` contract:

```json
{
  "request_id": "uuid",
  "trace_id": "uuid",
  "status": "pending_review",
  "response": "Grounded response text",
  "citations": [],
  "confidence": 0.84,
  "confidence_details": {},
  "model_used": "aiprimetech:claude-opus-5",
  "requires_review": true,
  "intent": "account_or_customer_action",
  "topic": "card_security",
  "risk_level": "high",
  "needs_retrieval": true,
  "needs_tools": true,
  "route_reason": "...",
  "tool_calls": [],
  "provider_attempts": [],
  "decision_factors": {},
  "escalation_reasons": [],
  "tokens_in": 0,
  "tokens_out": 0,
  "stage_timings": {},
  "latency_ms": 0,
  "estimated_cost": 0,
  "created_at": "ISO-8601",
  "completed_at": "ISO-8601 or null"
}
```

Each citation includes `document_id`, `chunk_id`, `title`, `source`, optional `page_number`, `chunk_index`, `excerpt`, and normalized `score`. Each provider attempt includes actual provider/model, purpose, route reason, tokens, latency, cost, retries, success, error, and timestamp.

### GET `/requests/{request_id}`

Returns the same complete contract. A missing ID returns `404`.

### PowerShell example

```powershell
$body = @{
  message = "How long does card replacement take?"
  user_id = "demo-user"
  channel = "web"
  metadata = @{ scenario = "github-demo" }
  routing_strategy = "cheapest_adequate"
} | ConvertTo-Json

$result = Invoke-RestMethod -Method Post `
  -Uri http://localhost:3000/api/v1/requests `
  -ContentType "application/json" `
  -Body $body

Invoke-RestMethod "http://localhost:3000/api/v1/requests/$($result.request_id)"
```

## Reviews

### GET `/reviews`

Query parameters:

- `status`: default `pending`; pass an empty/omitted filter through a client that supports it to retrieve all states;
- `limit`: 1–500, default 100.

Evaluation-tagged traffic is excluded. Each item includes review/request states, original message/response, classification, risk, citations, score, route, notes, edited response, error/recovery state, decision history, and timestamps.

### POST `/reviews/{review_id}/approve`

```json
{ "reviewer_notes": "Evidence and safety steps verified." }
```

### POST `/reviews/{review_id}/reject`

```json
{ "reviewer_notes": "Source conflict requires policy-owner clarification." }
```

### POST `/reviews/{review_id}/edit-and-approve`

```json
{
  "reviewer_notes": "Removed an unsupported claim.",
  "edited_response": "Approved edited response."
}
```

`reviewer_notes` is optional and limited to 4,000 characters. `edited_response` is required, trimmed, and limited to 50,000 characters by the API contract (the current UI editor applies an 8,000-character operator limit).

Concurrent/already-resolved decisions return `409`. A recoverable decision persistence failure returns `503` with `Retry-After: 2`.

## Knowledge Base

### POST `/knowledge/documents`

Multipart fields:

- `file` — required TXT, Markdown, or PDF;
- `title` — optional, maximum 300 characters;
- `source` — optional, default `upload`, maximum 500 characters;
- `metadata_json` — JSON object string, maximum 16,384 characters.

```bash
curl --fail-with-body \
  -F "file=@data/demo_documents/card_replacement_procedure.md" \
  -F "title=Card Replacement Procedure" \
  -F "source=Operations Manual" \
  -F 'metadata_json={"environment":"demo"}' \
  http://localhost:3000/api/v1/knowledge/documents
```

Returns `201` only after the atomic parse/chunk/embed/index transaction succeeds. Invalid or partial uploads are not retained.

### GET `/knowledge/documents`

| Parameter | Default | Limit |
| --- | ---: | ---: |
| `limit` | 100 | 1–500 |
| `offset` | 0 | ≥ 0 |
| `search` | none | 300 characters |
| `source` | none | 500 characters |

Search matches title or filename case-insensitively. Source is an exact metadata-source filter.

### GET `/knowledge/documents/{document_id}`

| Parameter | Default | Limit |
| --- | ---: | ---: |
| `content_offset` | 0 | ≥ 0 |
| `content_limit` | 200,000 | 0–500,000 |
| `chunk_offset` | 0 | ≥ 0 |
| `chunk_limit` | 50 | 0–100 |

The response includes normalized text, ordered chunks, totals, completion booleans, and next offsets. Use `content_limit=0` or `chunk_limit=0` when only the other representation is needed.

### DELETE `/knowledge/documents/{document_id}`

Returns `{ "id": "...", "deleted": true }`. Missing documents return `404`. Upload and delete return `409` while an evaluation holds the knowledge snapshot guard.

## Evaluations

### POST `/evals/run`

```json
{
  "name": "Synthetic benchmark v6",
  "configurations": ["baseline", "improved"],
  "max_cases": null
}
```

Optional `cases` can provide 1–100 explicit case contracts. `configurations` contains one or both supported names. The endpoint is synchronous for normal completion and returns `201` with results.

If an identical fingerprint is already `running`, the endpoint returns `202 Accepted`, the existing run, `Location: /api/v1/evals/runs/{id}`, and `Retry-After: 2`. Poll until `completed`, `invalid`, or `failed`.

### GET `/evals/runs`

`limit` defaults to 50 and accepts 1–200. List responses omit the large `results` collection.

### GET `/evals/runs/{run_id}`

Returns configuration/provenance, summary, timestamps, and all persisted result rows. Each result contains configuration, case/model identity, metric values, latency, cost, pass state, and detailed gates/failures.

## Metrics and models

### GET `/metrics/summary`

Returns total/successful operational requests, success/escalation/error/retrieval-hit rates, average/P95 latency, tokens, estimated spend, pending reviews, timeline points, and recent traces.

### GET `/metrics/models`

Returns provider/model call count, success rate, average latency, input/output tokens, and estimated spend.

### GET `/models`

Returns non-secret registry entries: display name, route role/description, context, capabilities, quality tier, expected latency, prices/source, enabled/fallback flags, and availability (`disabled`, `local`, or `configured_unverified`).

This endpoint does not transmit credentials to a provider and must not be interpreted as live provider readiness.

## Health

### GET `/health`

```json
{
  "status": "ok",
  "database": "ok",
  "provider": "configured_unverified",
  "provider_mode": "aiprimetech",
  "version": "0.1.0"
}
```

Provider states:

- `local` — explicit deterministic mock mode;
- `fallback` — auto mode has no remote credential and will use local mock;
- `configured_unverified` — remote credential is configured, but health did not make a third-party request;
- `error` — explicit provider mode is missing its credential.

Database or provider configuration error produces status `degraded` and HTTP `503`.

## Common errors

| HTTP | Meaning |
| ---: | --- |
| 404 | Request, review, document, or evaluation run does not exist. |
| 409 | Concurrent review decision or knowledge mutation during evaluation. |
| 413 | Message, metadata, or upload exceeds a configured limit. |
| 415 | Unsupported or mismatched upload type. |
| 422 | Schema validation, invalid explicit model, metadata JSON, or evaluation dataset error. |
| 429 | Rate limit exceeded; inspect `Retry-After`. |
| 503 | Degraded health or recoverable backend/provider operation failure. |

Errors use safe messages and never intentionally include provider keys.
