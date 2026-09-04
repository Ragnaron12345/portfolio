# Architecture

## System boundary

Flowline separates orchestration from reusable domain behavior.

- **n8n** owns webhook choreography, explicit route visibility, bounded HTTP transport retry, orchestration outcome audit, and the shared workflow-level failure handler.
- **FastAPI** owns strict request/response schemas, AI-provider calls, structured-output repair, deterministic rules, risk policy, approval gating, idempotent integrations, persistence, sanitization, metrics, and API contracts.
- **PostgreSQL** is authoritative for execution state. The UI and n8n never invent completion state.
- **React/nginx** is an operator surface. It uses only the public API and stores selected execution/review identity in URL state.
- **Mock systems** model CRM, ERP, Jira, and Slack locally while recording the originating execution ID.

The deliberate rule is: **n8n orchestrates; reusable AI and business logic live in custom services.**

## Request lifecycle

~~~mermaid
sequenceDiagram
    autonumber
    participant UI as React UI
    participant API as FastAPI public ingress
    participant DB as PostgreSQL
    participant N as n8n webhook
    participant D as FastAPI internal domain endpoint
    participant P as AI + policy services
    participant X as Mock external system

    UI->>API: POST /api/v1/runs/{workflow}
    API->>API: Strict Pydantic validation and sanitization
    API->>DB: Create received execution + correlation ID
    API->>N: Envelope {execution_id, correlation_id, workflow, payload}
    N->>N: Validate orchestration envelope
    N->>D: POST /api/v1/internal/runs/{workflow}
    Note over N,D: X-Internal-Token, max 3 transport attempts
    D->>DB: Lock and transition existing execution
    D->>P: Provider call + schema validation + deterministic policy
    P-->>D: Structured result or exact typed error
    alt automated action is allowed
        D->>X: Idempotent allowlisted action
        D->>DB: completed / completed_with_warning
    else human review required
        D->>DB: approval + waiting_for_review
    else failure exhausted
        D->>DB: exact error + failed
    end
    D-->>N: Full execution object
    N->>N: Explicit success/review/failure/dedup branch
    N->>API: POST orchestration audit
    N-->>API: Webhook response with execution_id
    API-->>UI: Authoritative execution state
    UI->>API: Poll selected execution by URL-stable ID
~~~

When `AUTOMATION_USE_N8N=false`, public ingress runs the same domain service directly. This is useful for backend tests, but Compose enables n8n so the production-style demo exercises the full loop.

## Execution state

Every execution persists:

- `execution_id` and `correlation_id`;
- workflow, current stage, status, timestamps, duration, and exact safe error;
- decision summary with reason and structured evidence;
- ordered execution events;
- AI calls with provider, model, purpose, attempt, latency, tokens, cost estimate, and outcome;
- approval and reviewer-decision history;
- external-action attempts;
- append-only audit events.

~~~mermaid
stateDiagram-v2
    [*] --> received
    received --> running
    received --> failed
    running --> running: stage transition
    running --> waiting_for_review: policy gate
    running --> completed: successful action
    running --> completed_with_warning: safe partial outcome
    running --> failed: exhausted failure
    waiting_for_review --> running: approve
    waiting_for_review --> cancelled: reject
    running --> completed: approved action
    running --> completed_with_warning: approved but action still blocked
~~~

Terminal state is written only after the required audit/action boundary. A n8n transport error cannot overwrite a domain execution as completed.

## Workflow-specific ownership

n8n orchestrates at the execution boundary: it validates the webhook envelope, invokes the protected workflow API with bounded transport retry, routes the authoritative completed/review/failed/deduplicated state, writes the matching audit outcome, and returns a webhook response. FastAPI deliberately owns the finer domain stages listed in the brief because it also owns structured model contracts, deterministic rules, transactions, idempotency, and side-effect gates. Each fine-grained transition is persisted and rendered in the operator timeline; none is hidden in n8n expression code. This coarse-grained boundary prevents the same policy from being implemented twice while keeping n8n-not the browser or provider-in control of orchestration and error routing.

| Concern | n8n | FastAPI |
|---|---:|---:|
| Webhook and visual branch topology | ✓ | |
| Internal transport retry (maximum 3) | ✓ | |
| Shared unhandled-error audit | ✓ | |
| Pydantic input/output validation | | ✓ |
| Provider retry/fallback (maximum 2 by default) | | ✓ |
| Support category/risk/reason | | ✓ |
| KB retrieval and relevance score | | ✓ |
| Invoice arithmetic and duplicate detection | | ✓ |
| Incident fingerprint and root-cause safety | | ✓ |
| Human approval and side-effect gate | | ✓ |
| Integration idempotency and audit persistence | | ✓ |

## Data model

~~~mermaid
erDiagram
    WORKFLOW_EXECUTIONS ||--o{ EXECUTION_EVENTS : contains
    WORKFLOW_EXECUTIONS ||--o{ AUDIT_EVENTS : explains
    WORKFLOW_EXECUTIONS ||--o{ AI_CALLS : measures
    WORKFLOW_EXECUTIONS ||--o{ APPROVAL_ITEMS : may_require
    APPROVAL_ITEMS ||--o{ REVIEW_DECISIONS : records
    WORKFLOW_EXECUTIONS ||--o{ EXTERNAL_ACTION_ATTEMPTS : invokes
    WORKFLOW_EXECUTIONS ||--o{ MOCK_TICKETS : originates
    WORKFLOW_EXECUTIONS ||--o{ MOCK_INVOICES : originates
    WORKFLOW_EXECUTIONS ||--o{ MOCK_INCIDENTS : originates
    MOCK_INCIDENTS ||--o{ MOCK_MESSAGES : notifies
~~~

n8n uses a separate `n8n` PostgreSQL schema. Application tables remain in the default schema. Named volumes preserve both datasets across normal Compose restarts.

## Failure model

| Failure | Owner and bounded behavior | Result |
|---|---|---|
| Invalid public payload | FastAPI strict model | HTTP 422; no side effect |
| Invalid orchestration envelope | n8n validation branch | Audit + HTTP 422 |
| Internal API timeout | n8n, at most 3 attempts | Exact transport error + audit |
| Provider timeout | provider manager, at most 2 attempts | fallback or exact failure |
| Malformed extraction | one structured repair retry | review; raw output hidden |
| Injected database operation error | FastAPI transaction | exact terminal failure + event/audit; no side effect |
| Physical database outage | API readiness/exception boundary | sanitized error; external service monitor required because the unavailable DB cannot store its own outage record |
| CRM/ERP/Jira/Slack error | idempotent integration wrapper | retry/warning/failure per policy |
| Unhandled n8n node error | shared Error Trigger workflow | sanitized failure audit with execution URL |

Retries at the transport and provider layers are intentionally separate and visible.

### Timing and concurrency invariant

The published n8n workflows have a 120-second execution ceiling. The longest configured AI path is bounded below that ceiling: two provider attempts, at most 12 seconds each, with one mock fallback and at most two AI stages. FastAPI waits 150 seconds for the synchronous n8n response, so it cannot mark an execution failed while the supported internal path is still eligible to commit. If a webhook response is lost after the domain transaction completes, FastAPI reloads the authoritative execution and records `n8n_dispatch_response_lost` instead of overwriting it. Repeated delivery is safe because the internal route locks the execution and returns its current state once it has left `received`.

## Network topology

~~~mermaid
flowchart TB
    HOST[127.0.0.1 only] --> UI[frontend :3004]
    HOST --> API[backend :8004]
    HOST --> N8N[n8n :5678]
    HOST --> PGPORT[PostgreSQL :5434 local debug only]
    subgraph edge
      UI
      API
      N8N
    end
    subgraph data_internal["data network - internal"]
      API
      N8N
      PG[(PostgreSQL)]
    end
~~~

For a production deployment, remove the PostgreSQL host mapping, put UI/API/n8n behind authenticated TLS, rotate the internal token and n8n encryption key, add an external secret manager, restrict n8n editor access, configure backups, and replace mock integrations with narrow service adapters.
