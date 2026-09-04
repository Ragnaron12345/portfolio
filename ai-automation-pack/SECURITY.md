# Security

## Trust boundaries

- Browser input, support messages, invoice content, monitoring events, and model output are **untrusted**.
- All external text is sanitized before persistence/display. Raw malformed AI output is never shown as final operator data.
- AI output cannot select a shell command, arbitrary URL, or non-allowlisted action.

## Controls

- Strict Pydantic models reject unknown fields, invalid enums, empty required values, oversized content, and malformed structured output.
- Invoice validation and incident deduplication are deterministic.
- High-risk, low-confidence, malformed, and policy-blocked work enters human review.
- Rejection never performs a side effect. Approval still passes deterministic gates.
- Side effects carry execution IDs and idempotency keys; bounded retries are recorded.
- Every automated decision carries a human-readable reason and audit context.
- Prompt-injection phrases are treated as document content — they cannot change system policy or credentials.

## Secrets

`.env`, `.env.local`, and `.env.*.local` are gitignored. Never commit keys.

- `OPENAI_API_KEY` belongs only in `.env.local` or a production secret manager.
- `AUTOMATION_INTERNAL_TOKEN` authenticates n8n to internal API routes.
- `N8N_ENCRYPTION_KEY` protects n8n credential storage.
- Do not expose secrets through `VITE_*` variables — those are bundled into browser JavaScript.
- Do not put secrets in workflow JSON, screenshots, logs, fixtures, docs, or Git history.

## Network controls

Compose binds all ports to `127.0.0.1`. PostgreSQL sits on an internal Docker network. For any shared deployment: remove PostgreSQL host port, place services behind authenticated TLS, restrict n8n editor to administrators, disable public n8n API, use a managed secret store, and configure encrypted backups.

## Local demo limitations

- The loopback-only operator console has no application login. It assumes one trusted local operator.
- Local mock systems do not represent vendor authentication, rate limits, or contractual controls.
- The internal token is shared between two local containers; production should use workload identity or short-lived credentials.
- Audit history is operational evidence. A regulated deployment needs append-only export, retention policy, and independent monitoring.

For the full trust model and deployment checklist, see the previous version of this file in Git history.
