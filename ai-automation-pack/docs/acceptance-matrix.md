# Acceptance scenarios

Each scenario maps a business rule to automated evidence. All runtime probes enter through the public FastAPI endpoint, cross the n8n webhook, and require a matching `n8n.*` audit event.

## Support triage

| Scenario | Expected behavior | Automated assertion |
|---|---|---|
| Stolen card | `suspected_fraud`, high risk, mandatory review, no auto customer action | `test_exact_stolen_card_case_requires_review_without_side_effect` |
| Approved stolen card | Internal escalation only, not customer-facing | `test_approved_stolen_card_only_creates_internal_escalation` |
| Prompt injection | Audited, blocked, no side effect | `test_prompt_injection_is_audited_and_side_effect_is_blocked` |
| Low-risk completion | CRM response created | `test_low_risk_support_is_grounded_and_completed` |
| Grounded draft required | Ungrounded output never reaches CRM | `test_ungrounded_provider_output_never_creates_crm_side_effect` |

## Invoice processing

| Scenario | Expected behavior | Automated assertion |
|---|---|---|
| Valid invoice | ERP receives exactly one invoice | Exact ERP mock count check |
| Arithmetic mismatch | ERP blocked, exact `€1,210 ≠ €1,000 + €190` message | Backend tests |
| Duplicate invoice | ERP blocked, no second insert | Duplicate detection test |
| Approved review | Side effects execute after approval | Approval integration test |

## Incident intelligence

| Scenario | Expected behavior | Automated assertion |
|---|---|---|
| New incident | Jira issue + Slack notification created | End-to-end probe |
| Duplicate burst | One Jira issue, occurrence count incremented | Dedup integration test |
| Low-confidence | Jira/Slack blocked until approval | Probe with fault injection |
| Provider failure | Retry visible, fallback audited, exact failure state | Fallback probe |

## Observability

| Requirement | Evidence |
|---|---|
| Metrics with units | Backend tests assert numeric rates, latency with ms units |
| Execution timeline | Every probe validates event sequence |
| Audit trail | `n8n.*` audit events required for every end-to-end probe |
| Retry visibility | Provider-retry events asserted with `raw_output_exposed: false` |

## Reproduce locally

~~~powershell
.\manage.ps1 Up
.\manage.ps1 Seed
.\manage.ps1 Demo
~~~

Service health: <http://localhost:8004/ready> · <http://localhost:5678/healthz> · <http://localhost:3004/healthz>
