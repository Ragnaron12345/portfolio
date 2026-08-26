# Security

Nexora is a local portfolio application, not a hardened public service. Its
security design demonstrates explicit trust boundaries and conservative failure
modes.

## Controls

- Secrets are loaded only from ignored local environment files.
- Provider credentials never enter frontend bundles, logs, health responses, or Git.
- Upload filenames, extensions, MIME types, byte size, decoded text, pages, and chunks are validated.
- OCR is local and does not transmit document images to a remote service.
- Retrieved text is treated as untrusted evidence, never as executable instruction.
- Tools are allowlisted and arguments are schema validated.
- High-risk, conflicting, unsupported, and low-confidence outcomes require review.
- Security, CORS, host, rate-limit, and no-store headers are applied consistently.
- Evaluation runs record provenance and reject concurrent corpus mutation.

## OCR-specific risks

OCR text can be incomplete, adversarial, or visually misleading. Entity values
therefore retain extraction confidence, pass explicit required-field validation,
and enter human review when confidence is below 0.85 or validation fails. The
original upload is not treated as an instruction source.

## Deployment boundary

Before public deployment, add authentication and authorization, encrypted object
storage, malware scanning, per-tenant isolation, durable queues, centralized
secret management, audit retention, database backups, and external penetration
testing. Replace the demo tools and synthetic documents before handling real data.

Report security issues privately to the repository owner. Do not include secrets,
customer data, or exploit payloads in a public issue.


