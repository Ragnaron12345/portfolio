# Security notes

DocIntel is a local portfolio system with explicit controls, not a hardened
public document-processing service.

## Implemented controls

- Secrets are loaded only from ignored server-side env files.
- Uploads are streamed in bounded chunks; byte limit is enforced server-side.
- Basenames are sanitized, storage names are random, and user paths are never used.
- Extension, MIME, and magic signatures are cross-checked.
- PDF page and decoded-image pixel limits reduce decompression/image-bomb risk.
- SHA-256 is stored for integrity and duplicate analysis.
- OCR runs locally; uploaded pixels are not sent to the LLM provider.
- Document content is wrapped as untrusted data and never treated as instruction.
- Provider URL, timeout, retry, and single-repair behavior are bounded.
- Pydantic schemas reject extra fields; deterministic rules control workflow decisions.
- Unsupported, malformed, low-confidence, and invalid outputs require review.
- Security, no-store, clickjacking, MIME-sniffing, and referrer headers are applied.
- Structured logs include trace ID, document ID, stage, latency, event, and status.

## Production additions

Before handling real PII add authentication/authorization, tenant isolation,
malware scanning, encrypted object storage, deletion/retention policies, durable
queues, centralized secrets, provider data-processing controls, redacted
central logs, rate limiting at the edge, backups, and independent security
testing.
