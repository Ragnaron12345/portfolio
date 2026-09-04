"""Acceptance probe for the support workflow through FastAPI -> n8n -> FastAPI."""

from __future__ import annotations

import uuid

from workflow_test_support import (
    assert_n8n_audit,
    deep_text,
    load_case,
    print_result,
    require,
    run_workflow,
)


def main() -> None:
    stolen = load_case("support_cases.json", "support-stolen-card")
    execution = run_workflow("support", stolen["input"])
    decision = execution.get("decision_summary", {})
    classification = decision.get("classification", {})
    sources = decision.get("sources", [])
    draft = str(decision.get("draft", ""))

    require(execution["status"] == "waiting_for_review", f"Stolen card was not routed to review: {execution}")
    require(classification.get("category") == "suspected_fraud", f"Unexpected category: {classification}")
    require(classification.get("risk_level") == "high", f"Unexpected risk: {classification}")
    reason = str(classification.get("reason", "")).casefold()
    require("stolen" in reason, f"Classification reason does not reference stolen card: {reason}")
    require(
        any(term in reason for term in ("security", "fraud", "risk")),
        f"Classification reason does not explain security risk: {reason}",
    )
    require(sources and all("relevance_score" in source for source in sources), f"Readable sources missing: {sources}")
    require("|---" not in draft and len(draft.strip()) > 20, f"Draft is missing or table-like: {draft}")
    require(any(term in draft.casefold() for term in ("freeze", "block")), f"Draft lacks protective action: {draft}")
    require(decision.get("automatic_customer_side_effect") is False, f"Unsafe automatic action: {decision}")
    require(execution.get("approvals"), f"Stolen-card execution has no approval item: {execution}")
    assert_n8n_audit(execution, "n8n.support.waiting_for_review")
    print_result(stolen["id"], execution)

    injection = load_case("support_cases.json", "support-prompt-injection")
    injected_execution = run_workflow("support", injection["input"])
    injected_text = deep_text(injected_execution)
    require(injected_execution["status"] == "waiting_for_review", "Prompt injection was not routed to review.")
    require("prompt_injection" in injected_text or "prompt injection" in injected_text, "Injection audit is missing.")
    require(
        injected_execution.get("decision_summary", {}).get("automatic_customer_side_effect") is False,
        "Prompt injection caused an automatic customer-facing side effect.",
    )
    assert_n8n_audit(injected_execution, "n8n.support.waiting_for_review")
    print_result(injection["id"], injected_execution)

    provider = load_case("support_cases.json", "support-provider-timeout")
    provider_execution = run_workflow("support", provider["input"])
    attempts = [call.get("attempt", 0) for call in provider_execution.get("ai_calls", [])]
    require(max(attempts, default=0) >= 2, f"Bounded provider retry is not visible: {attempts}")
    require(provider_execution["status"] != "failed", f"Configured fallback did not recover: {provider_execution}")
    assert_n8n_audit(provider_execution, "n8n.support.")
    print_result(provider["id"], provider_execution)

    failure_execution = run_workflow(
        "support",
        {
            "ticket_id": f"T-CRM-FAIL-{uuid.uuid4().hex[:8]}",
            "customer_id": "CUST-FAIL",
            "subject": "Replacement timing",
            "message": "How long does card replacement take?",
            "fault_profile": "crm_failure",
        },
    )
    require(failure_execution["status"] == "failed", f"CRM failure was hidden: {failure_execution}")
    require("crm" in deep_text(failure_execution.get("error")), failure_execution)
    require(
        any(not action.get("success", True) for action in failure_execution.get("external_actions", [])),
        f"Failed CRM attempt is absent: {failure_execution}",
    )
    assert_n8n_audit(failure_execution, "n8n.support.failed")
    print_result("support-crm-failure", failure_execution)

    database_execution = run_workflow(
        "support",
        {
            "ticket_id": f"T-DB-FAIL-{uuid.uuid4().hex[:8]}",
            "customer_id": "CUST-FAIL",
            "subject": "Replacement timing",
            "message": "How long does card replacement take?",
            "fault_profile": "database_failure",
        },
    )
    require(database_execution["status"] == "failed", database_execution)
    require("database_operation_failed" in deep_text(database_execution.get("error")), database_execution)
    require(not database_execution.get("external_actions"), "Database fault reached an external adapter.")
    assert_n8n_audit(database_execution, "n8n.support.failed")
    print_result("support-database-failure", database_execution)

    print("PASS support: stolen-card, injection, provider retry, database, and CRM failure paths")


if __name__ == "__main__":
    main()
