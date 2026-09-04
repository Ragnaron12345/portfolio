# Flowline — AI Automation Pack

Production-style AI workflow orchestration with n8n, custom FastAPI services, human approval, deterministic validation, integrations and auditability.

**n8n orchestrates; reusable AI and business logic live in custom services.**

Flowline is a portfolio-grade, locally runnable operations console for three end-to-end automations: AI support triage, invoice processing, and incident intelligence. Every run has a correlation ID, visible stages, structured decisions, bounded retries, human-review gates, external-action records, and an audit trail. Mock AI, CRM, ERP, Jira, and Slack implementations make the complete demo work without paid SaaS.

![Flowline workflow operations](docs/images/overview-runtime.png)

## TL;DR — What this project proves

- A real FastAPI → n8n → FastAPI orchestration loop, rather than decorative workflow screenshots.
- Strict Pydantic input and AI-output contracts with operator-readable reasons.
- High-risk and low-confidence actions stop at human review.
- Invoice arithmetic, required fields, dates, currencies, and duplicates are checked deterministically.
- Incident fingerprints suppress duplicate Jira issues while preserving occurrence history.
- Provider, transport, database, and mock-system failures remain visible and auditable.
- Numeric operational metrics, full execution timelines, approvals, audit history, and mock-system state.
- A deterministic offline mode plus an optional OpenAI-compatible provider.

## How it demonstrates system analysis skills

| Skill | Evidence in the project |
|---|---|
| Requirements clarity | Every workflow has explicit input contracts, deterministic validation rules, and human-review gates — no ambiguous "it works somehow" |
| Data quality control | Invoice arithmetic checks, confidence-gated actions, required-field validation — bad data is caught before any side effect |
| Risk management | High-risk classifications require human approval; automatic actions are blocked by policy gates |
| Observability | Metrics show numbers/units; every execution has a visible timeline, retry count, and audit trail |
| Integration thinking | API boundary between n8n (orchestration) and FastAPI (domain logic) — each layer has a clear responsibility |
| Testing strategy | Unit tests for validation logic, integration probes for end-to-end paths, acceptance cases for edge scenarios |

## Architecture

~~~mermaid
flowchart LR
    UI[React operator console] -->|public API| API[FastAPI ingress]
    API -->|create execution| PG[(PostgreSQL)]
    API -->|validated envelope| N8N[n8n orchestration]
    N8N -->|internal token + execution ID| DOMAIN[FastAPI domain workflows]
    DOMAIN --> AI{Provider manager}
    AI --> MOCK[Deterministic mock AI]
    AI --> OPENAI[OpenAI-compatible API]
    DOMAIN --> POLICY[Validation and policy gates]
    POLICY --> REVIEW[Human approval]
    POLICY --> SYSTEMS[Mock CRM / ERP / Jira / Slack]
    DOMAIN --> PG
    N8N -->|outcome audit| PG
    UI -->|poll by stable URL selection| API
~~~

The public run endpoint first persists an execution, then calls the matching n8n webhook. n8n validates the orchestration envelope, calls a protected internal domain endpoint with a bounded retry, branches on completed/review/failed/deduplicated state, writes an orchestration audit event, and returns the execution ID. FastAPI owns the fine-grained domain stages and persists every transition; n8n owns the execution boundary and outcome routing, avoiding duplicated policy in expression code. The internal token prevents recursion and is never exposed to the browser.

## Workflows

~~~mermaid
flowchart TB
    subgraph Support["AI Support Triage"]
      S1[Validate ticket] --> S2[Classify with reason]
      S2 --> S3[Retrieve readable policy sources]
      S3 --> S4[Generate and validate grounded draft]
      S4 -->|high risk / uncertain / injection| S5[Human review]
      S4 -->|low risk + high confidence| S6[Idempotent CRM response]
    end

    subgraph Invoice["Invoice Processing"]
      I1[Extract strict fields] --> I2[Deterministic checks]
      I2 --> I3[Duplicate check]
      I3 -->|valid and unique| I4[Idempotent ERP submit]
      I2 -->|mismatch / missing / malformed| I5[Human review]
      I3 -->|duplicate| I5
    end

    subgraph Incident["Incident Intelligence"]
      N1[Validate event] --> N2[Fingerprint and deduplicate]
      N2 -->|existing| N3[Update occurrence]
      N2 -->|new| N4[Safe structured summary]
      N4 -->|low confidence| N7[Human review]
      N4 -->|high confidence| N5[Jira issue]
      N7 -->|approved| N5
      N5 --> N6[Slack notification]
    end
~~~

## Key acceptance cases

**Stolen card** → `suspected_fraud`, high risk, mandatory review, no automatic customer-facing side effect

**Bad invoice** (€1,210 ≠ €1,000 + €190) → exact mismatch message, ERP blocked, review created

**Duplicate incident** → one Jira issue created, second event records "Deduplicated into INC-…"

**Provider failure** → retry visible, fallback audited, exact failure state, never falsely completed

## Run locally

Requirements: Docker Desktop, 4 GB free memory, Python 3.12+ for scripts.

~~~powershell
.\manage.ps1 Setup
# Replace placeholder values in .env
.\manage.ps1 Up
.\manage.ps1 Seed
.\manage.ps1 Demo
~~~

Default URLs:
- Operator UI: <http://localhost:3004>
- FastAPI health: <http://localhost:8004/health>
- n8n editor: <http://localhost:5678>

## Provider configuration

Mock mode is the default. To use OpenAI, add to `.env.local`:

~~~dotenv
AUTOMATION_AI_PROVIDER=openai
AUTOMATION_AI_FALLBACK_PROVIDER=mock
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
~~~

Never put keys in workflow JSON, screenshots, documentation, or Git history.

## Demo and verification

~~~powershell
# Static workflow validation
python scripts/validate_workflows.py

# Backend tests
Set-Location automation-api; python -m pytest; Set-Location ..

# End-to-end probes (requires running Compose stack)
python scripts/test_support_workflow.py
python scripts/test_invoice_workflow.py
python scripts/test_incident_workflow.py
~~~

## Repository map

~~~text
automation-api/   FastAPI, Pydantic, persistence, policies, AI and mock integrations
frontend/         React + TypeScript operator console served by nginx
workflows/        Importable and published n8n JSON workflows
fixtures/         Synthetic support, invoice, incident, and knowledge data
scripts/          Workflow import, validation, and end-to-end probes
docs/             Architecture, API, workflow and visual documentation
~~~

No real customer, invoice, incident, or credential data is included. See [SECURITY.md](SECURITY.md) for the trust model and deployment checklist. MIT license.
