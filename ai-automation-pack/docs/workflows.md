# n8n workflows

The `workflows/` directory contains four importable exports pinned to the n8n 2.x runtime in Compose.

| File | Stable ID | Published webhook |
|---|---|---|
| `00-shared-error-handler.json` | `ErrHandler202609` | Error Trigger only |
| `01-ai-support-triage.json` | `SupportFlow2609` | `POST /webhook/support-triage` |
| `02-invoice-processing.json` | `InvoiceFlow2609` | `POST /webhook/invoice-processing` |
| `03-incident-intelligence.json` | `IncidentFlow260` | `POST /webhook/incident-intelligence` |

Compose runs `scripts/n8n-init.sh` before the n8n service. It imports each JSON separately and uses the n8n 2.x `publish:workflow` command. The persistent n8n volume keeps editor state; stable workflow IDs make re-import deterministic.

Manual ensure/import (existing editor-owned versions are preserved):

~~~powershell
.\scripts\import_workflows.ps1
~~~

## Shared envelope

Public FastAPI ingress creates the execution first, then posts:

~~~json
{
  "execution_id": "opaque-backend-id",
  "correlation_id": "caller-or-generated-id",
  "workflow": "support",
  "payload": {}
}
~~~

A webhook never trusts a caller-supplied action URL. The only destination is `$env.AUTOMATION_API_INTERNAL_URL` and the internal token is read from `$env.AUTOMATION_INTERNAL_TOKEN`. Neither value is embedded in an export.

## Common branch topology

~~~mermaid
flowchart LR
    W[Receive webhook] --> V{Valid envelope?}
    V -->|no| IA[Audit invalid payload]
    IA --> R422[Return 422 with execution ID]
    V -->|yes| C[Call protected internal run]
    C -. max 3 attempts .-> C
    C --> E{Execution response?}
    E -->|no| TA[Audit exhausted retries]
    TA --> R502[Return exact 502 failure]
    E -->|yes| F{Failed?}
    F -->|yes| FA[Audit failed state]
    F -->|no| P{Needs review / domain branch?}
    FA --> R200[Return execution]
    P --> OA[Audit orchestration outcome]
    OA --> R200
~~~

Unhandled node errors use `ErrHandler202609`. It captures a sanitized message, failed node, workflow name, n8n execution ID and execution URL, then makes at most three attempts to persist a failure audit. It omits raw model output and provider secrets.

## AI Support Triage

Visible nodes communicate the contract:

1. **Receive Support Request**
2. **Validate Orchestration Envelope**
3. **Run Classification Retrieval and Draft**
4. **Execution Response Available**
5. **Execution Failed**
6. **Risk Policy Requires Review**
7. a distinct audit and response node for completed, review, failed, retry-exhausted, and invalid paths

The single internal API call performs strict ticket validation, prompt-injection detection, provider classification, KB retrieval, grounded drafting, validation, deterministic risk policy, approval creation, and CRM idempotency. This keeps prompts and business policy reusable and testable outside n8n.

High risk, prompt injection, insufficient confidence, unsafe draft, or configured medium risk enters `waiting_for_review`. High-risk work has no automatic customer-facing action.

## Invoice Processing

The workflow makes these routes explicit:

- extraction/validation completed and ERP submission recorded;
- deterministic mismatch/duplicate/missing-field/malformed extraction enters review;
- provider or ERP failure returns a true failed state;
- internal transport failure returns an exact 502 after bounded retry.

FastAPI performs `subtotal + tax ≈ total` with decimal arithmetic and configured tolerance. It also checks required fields, date, currency, extraction confidence, and normalized vendor/invoice-number duplication. One malformed-output repair attempt is permitted. Raw malformed output is not returned.

## Incident Intelligence and Escalation

After safe internal execution, n8n branches again on **Was Incident Deduplicated**. A duplicate writes `n8n.incident.deduplicated`; a new event writes `n8n.incident.created`. Both return the same execution contract.

FastAPI owns normalized fingerprinting, the time window, safe summary validation, idempotent Jira/Slack calls, and occurrence updates. Possible causes must begin with “Possible:” or “Hypothesis:” and confirmed-root-cause wording is rejected unless source evidence supports it.

## Retry boundaries

| Layer | Limit | Reason |
|---|---:|---|
| n8n → internal FastAPI transport | 3 attempts | transient HTTP/network failure |
| AI provider structured call | 2 attempts by default | timeout or one repair attempt |
| local external adapter | bounded per adapter | demonstrate transient/terminal integration behavior |

The workflow JSON uses `retryOnFail`, `maxTries` and `waitBetweenTries`. The error output continues only into an explicit transport-failure branch; audit writes themselves fail loudly into the shared error handler.

## Validation

~~~powershell
python scripts/validate_workflows.py
docker compose config --quiet
.\manage.ps1 Up
.\manage.ps1 Demo
~~~

Static validation checks JSON parsing, unique node IDs/names, connection targets, shared error wiring, webhook response mode, explicit IF branches, bounded internal retries, audit nodes, and likely embedded secrets. Only successful CLI import/publication and the full-chain probes prove runtime behavior.
