# API

The FastAPI schema is available locally at `http://localhost:8001/api/v1/docs`.
All application routes use the `/api/v1` prefix.

## Core endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/requests` | Run classification, retrieval, routing, tools, generation, and review policy. |
| `GET` | `/requests/{id}` | Read a persisted request trace and provider/tool evidence. |
| `GET` | `/reviews` | List pending or resolved human-review items, including document-AI reviews. |
| `POST` | `/reviews/{id}/approve` | Approve an item. |
| `POST` | `/reviews/{id}/reject` | Reject an item. |
| `POST` | `/reviews/{id}/edit-and-approve` | Persist a corrected response and approve it. |
| `POST` | `/knowledge/documents` | Upload text, Markdown, PDF, PNG, or JPEG for extraction and indexing. |
| `GET` | `/knowledge/documents` | List indexed documents and document-AI metadata. |
| `GET` | `/knowledge/documents/{id}` | Read extracted content and paginated chunks. |
| `DELETE` | `/knowledge/documents/{id}` | Delete a document and its chunks. |
| `POST` | `/evals/run` | Run `regression` or `held_out` evaluation. |
| `GET` | `/evals/runs` | List persisted evaluation runs. |
| `GET` | `/evals/runs/{id}` | Read metrics and per-case evidence. |
| `GET` | `/models` | Read configured routing capabilities and prices. |
| `GET` | `/metrics/summary` | Read operational KPIs. |
| `GET` | `/health` | Check database and provider configuration state. |

`POST /knowledge/documents` accepts multipart field `document_type` with
`auto` (default), `general`, or `invoice`. `general` bypasses entity extraction;
`invoice` forces the invoice schema; `auto` applies the deterministic document
router after native extraction or OCR.

## Document-AI upload response

Native-PDF and OCR invoice processing is reported under `metadata.document_ai`.
Both paths expose common extraction fields; OCR adds compatibility-specific
`ocr_engine` and `ocr_confidence` fields:

```json
{
  "extraction_method": "ocr",
  "document_type": "invoice",
  "extraction_engine": "tesseract",
  "extraction_confidence": 0.91,
  "ocr_engine": "tesseract",
  "ocr_confidence": 0.91,
  "entity_confidence": 0.94,
  "entities": {
    "document_type": "invoice",
    "invoice_number": "INV-2048",
    "invoice_date": "2026-08-20",
    "currency": "EUR",
    "total": 149.9
  },
  "validation": {"valid": true, "errors": []},
  "requires_human_review": false
}
```

General PDFs and images expose the resolved routing decision without invoice
entities or validation errors and proceed directly to RAG indexing.

The API returns `422` for invalid input, `409` when knowledge mutation conflicts
with an evaluation, `413` for configured size limits, and `429` for rate limits.
Responses include `X-Trace-ID`; long-running duplicate evaluation attempts return
`202`, `Location`, and `Retry-After`.


