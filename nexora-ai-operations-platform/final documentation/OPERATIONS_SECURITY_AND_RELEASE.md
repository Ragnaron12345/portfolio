# Operations, Security, and Release

## Deployment status

Nexora is ready as a local portfolio/demo application. It is not ready for unauthenticated public exposure or real customer data.

The required local topology is:

- React production bundle served by nginx;
- FastAPI backend;
- PostgreSQL with pgvector;
- optional internal Redis profile.

Published ports bind to loopback in Compose. The frontend calls the relative `/api/v1` path, which nginx proxies to the backend.

## Prerequisites

- Docker Desktop or Docker Engine
- Docker Compose v2.24+
- 4 GB or more free memory
- PowerShell 7 for `manage.ps1`
- optional local development: Python 3.12+, Node.js 22+, pnpm 11.19, GNU Make

## Configuration

Create the non-secret local configuration without overwriting an existing file:

```powershell
.\manage.ps1 Setup
```

Replace the generated PostgreSQL password with a long URL-safe value. The tracked `.env.example` must contain no usable secret.

### Provider modes

| Mode | Behavior |
| --- | --- |
| `mock` | Deterministic local generation and local-hash embeddings. Best for CI/regression. |
| `auto` | Use configured remote provider; otherwise use deterministic fallback. |
| `aiprimetech` | Require the AI Prime credential and use its OpenAI-compatible chat endpoint. |
| `openai` | Require the OpenAI credential and use the configured OpenAI-compatible generation/embedding path. |

AI Prime uses an ignored `.env.aiprimetech.local` file:

```dotenv
AIPRIMETECH_API_KEY=<set-at-runtime>
NEXORA_AI_PROVIDER_MODE=auto
NEXORA_AIPRIMETECH_REQUEST_TIMEOUT_SECONDS=90
NEXORA_AIPRIMETECH_MAX_PROVIDER_RETRIES=0
```

OpenAI uses an ignored `.env.local` file:

```dotenv
OPENAI_API_KEY=<set-at-runtime>
NEXORA_AI_PROVIDER_MODE=openai
```

Never place a real key in documentation, `.env.example`, frontend variables, screenshots, issue text, shell transcripts, or Git history. AI Prime and OpenAI deliberately use different secret names.

## Start, seed, and stop

```powershell
.\manage.ps1 Up
.\manage.ps1 Seed
Invoke-RestMethod http://localhost:3000/api/v1/health
```

Endpoints:

- dashboard: <http://localhost:3000>
- API docs: <http://localhost:3000/api/v1/docs>
- direct backend: <http://localhost:8001/api/v1/health>

Seed the corpus and persisted 40-case comparison:

```powershell
.\manage.ps1 SeedEval
```

Optional Redis:

```powershell
.\manage.ps1 UpCache
```

Stop while preserving the PostgreSQL volume:

```powershell
.\manage.ps1 Down
```

`docker compose down -v` deletes the local database volume and is intentionally not wrapped by the task runner.

## Health interpretation

```powershell
Invoke-RestMethod http://localhost:3000/api/v1/health
```

- `status=ok` means database access and provider configuration checks passed.
- `provider=local` means explicit mock mode.
- `provider=fallback` means auto mode has no remote key and will use local mock.
- `provider=configured_unverified` means a remote route is configured, but health did not transmit the secret to verify the live external catalog.
- `provider=error` produces degraded health when an explicit provider mode lacks its credential.

Use an explicit, controlled provider request when live third-party readiness must be proven. Do not change health into a credentialed call that runs on every probe.

## Development verification

PowerShell task runner:

```powershell
.\manage.ps1 Lint
.\manage.ps1 Test
.\manage.ps1 Frontend
.\manage.ps1 Config
```

GNU Make equivalents:

```bash
make lint test frontend-check config
```

Direct frontend checks:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run test
pnpm run build
```

The verified local implementation includes:

- backend test suite: 91 tests passed after the final formatting patch, including answer emphasis sanitization;
- frontend tests: 29 passed after the patch;
- frontend typecheck and production build: passed after the patch;
- backend/frontend Docker image builds and container health: passed after the patch;
- desktop routes and 390 × 844 mobile navigation: checked without relevant browser console errors;
- post-patch Knowledge Base rendering: semantic headings/tables present, raw Markdown table delimiters absent;
- post-patch review response: existing `**` markers removed from the editable operator view.

Run the full CI-equivalent suite again on the final commit before tagging a release.

## CI

`.github/workflows/ci.yml` runs:

- Ruff;
- pytest;
- frontend typecheck/tests/build;
- Docker Compose configuration validation;
- backend and frontend image builds.

CI uses deterministic mock mode and requires no paid AI credential. The project is initialized as a Git repository on the `main` branch; verify the corresponding GitHub Actions run after every push.

## Logging and observability runbook

The service emits structured JSON logs and persists operational evidence in PostgreSQL. Investigate by trace ID:

1. copy the trace/request ID from Overview or Request Console;
2. call `GET /api/v1/requests/{request_id}`;
3. inspect classification/risk reasoning;
4. inspect retrieved citations and stage timing;
5. inspect every provider attempt, error, retry, tokens, and cost;
6. inspect tool arguments/results and approval status;
7. inspect workflow-score components and escalation reasons;
8. open the linked review item if release was blocked.

Operational metrics exclude evaluation-tagged traffic. A high success rate means technical completion, not semantic correctness.

## Failure runbooks

### Provider timeout or malformed output

- Confirm the actual provider attempts in the request record.
- Verify timeout/retry settings and selected model route.
- Confirm that the bounded fallback ran.
- Treat degraded local-fallback output below the required quality tier as review-only.
- Do not reclassify a failed provider attempt as an automatic success.

### Missing or weak evidence

- Inspect citation scores and source identity.
- Confirm that the relevant document is indexed in the same embedding space.
- Search/open the complete document and indexed chunks.
- Add or replace authoritative knowledge rather than weakening the release gate blindly.

### Evaluation stuck in `running`

- Poll the run URL returned in `Location`.
- Do not start an identical second run; duplicate protection returns the active run.
- After a backend restart, abandoned synchronous runs are marked `failed` with an abandonment reason.
- Confirm that knowledge mutation is available again after terminal state.

### Review decision failure

- Reload the item and inspect `decision_error` and history.
- Acknowledge evidence again before retrying.
- A conflict indicates another decision won; do not overwrite it.

## Security model

### Current trust boundaries

- untrusted browser/API input;
- untrusted uploaded documents and parsers;
- untrusted retrieved text;
- external provider output;
- tool names/arguments/results;
- unauthenticated local review workflow.

### Implemented controls

- strict Pydantic schemas and input limits;
- upload extension/MIME agreement, safe basename, text/page/chunk caps;
- atomic ingestion;
- explicit CORS, trusted-host validation, CSP and security headers;
- in-process rate limiting;
- server-only environment credentials;
- bounded timeouts/retries and token/context limits;
- static three-tool allowlist;
- no arbitrary code, shell, SQL, or unrestricted HTTP tool;
- retrieved/tool content treated as data, not instruction;
- structured provider-output validation and fallback;
- React-safe text rendering with no model-authored HTML injection;
- high-risk/weak-evidence/unsupported/failure review gates;
- persisted request/provider/tool/review audit evidence;
- synthetic customer and policy data.

### Not implemented / required before production

- authentication, reviewer identity, tenant/account authorization, and RBAC;
- TLS termination and deployment-specific network policy;
- managed secrets and rotation automation;
- output DLP/redaction and retention/deletion policy;
- distributed rate limits, per-user quotas, concurrency and cost budgets;
- durable background jobs, cancellation, and distributed leases;
- file signatures, malware/polyglot scanning, parser isolation/time limits;
- dependency/container scanning, SBOM, signing, and provenance attestations;
- backup/restore drills and monitoring/alerting;
- independent penetration testing and adversarial AI assessment.

Do not expose the current application publicly as-is.

## Secret incident procedure

If a secret is exposed:

1. revoke and rotate it immediately;
2. remove it from the current tree and Git history;
3. invalidate affected sessions/tokens;
4. inspect provider and application audit logs;
5. document scope and corrective controls privately.

A follow-up commit does not make a committed secret private.

## GitHub publishing checklist

### Repository hygiene

- [ ] Initialize Git in the project root, not in a parent directory containing unrelated work.
- [ ] Confirm `.gitignore` excludes `.env`, `.env.local`, `.env.*`, databases, caches, build artifacts, and local provider files.
- [ ] Confirm `.dockerignore` excludes credentials and development state.
- [ ] Run a secret scan across staged files and history.
- [ ] Verify no screenshots, logs, or exported artifacts contain keys or real customer data.
- [ ] Do not add `.env.aiprimetech.local` or `.env.local`, even to a private repository.

### Evidence and quality

- [ ] Run all backend and frontend checks on the exact staged commit.
- [ ] Run `docker compose config` and build both application images.
- [ ] Start from a clean volume and verify setup, migration, seed, request, review, KB, and evaluation flows.
- [ ] Confirm API docs and all five UI routes load without console errors.
- [ ] Confirm current benchmark tables match a persisted run and state their limitations.
- [ ] Update screenshots only from the running implementation.
- [ ] Verify every Markdown link and image path in README/final documentation.

### GitHub setup

- [ ] Create the repository and set the default branch to `main`.
- [ ] Add the MIT license and security reporting route.
- [ ] Push the first commit and wait for GitHub Actions to pass.
- [ ] Enable Dependabot/dependency review and secret scanning where available.
- [ ] Consider branch protection requiring CI before merge.
- [ ] Add topics such as `fastapi`, `react`, `rag`, `llm-evaluation`, `model-routing`, and `human-in-the-loop`.

### Release statement

Describe the project as a **production-oriented local portfolio system**. Do not call it production-ready, security-certified, or generally accurate. Distinguish deterministic regression evidence from provider-backed production results.

## Suggested GitHub description

> Production-oriented AI operations platform demonstrating RAG, explainable model routing, safe tool calling, human review, observability, and persisted baseline/improved evaluation evidence.
