"""Acceptance probe for incident creation and deterministic deduplication."""

from __future__ import annotations

import copy
import uuid

from workflow_test_support import (
    assert_n8n_audit,
    deep_text,
    list_items,
    load_case,
    print_result,
    request_json,
    require,
    run_workflow,
)


def main() -> None:
    case = load_case("incident_cases.json", "incident-duplicate-burst")
    payload = copy.deepcopy(case["input"])
    payload["service"] = f"checkout-demo-{uuid.uuid4().hex[:8]}"

    before = len(list_items("/mock/jira/issues"))
    first = run_workflow("incident", payload)
    after_first = len(list_items("/mock/jira/issues"))
    second = run_workflow("incident", payload)
    after_second = len(list_items("/mock/jira/issues"))

    require(first["status"] in {"completed", "completed_with_warning"}, f"First incident failed: {first}")
    require(after_first == before + 1, "First unique event did not create exactly one Jira incident.")
    require(second["status"] == "completed_with_warning", f"Duplicate event has wrong state: {second}")
    require("deduplicat" in deep_text(second.get("decision_summary", {})), f"Target incident is absent: {second}")
    require(after_second == after_first, "Duplicate event created a second Jira issue.")
    assert_n8n_audit(second, "n8n.incident.deduplicated")
    print_result(case["id"], second)

    outage = load_case("incident_cases.json", "incident-payment-outage")
    outage_payload = copy.deepcopy(outage["input"])
    outage_payload["service"] = f"payments-demo-{uuid.uuid4().hex[:8]}"
    outage_execution = run_workflow("incident", outage_payload)
    text = deep_text(outage_execution)
    require(outage_execution["status"] in {"completed", "completed_with_warning"}, outage_execution)
    require("possible:" in text or "hypothesis:" in text, "Possible causes are not labeled as hypotheses.")
    require("root cause is" not in text and "confirmed cause" not in text, "An unconfirmed root cause was asserted.")
    assert_n8n_audit(outage_execution, "n8n.incident.")
    print_result(outage["id"], outage_execution)

    review_before_jira = len(list_items("/mock/jira/issues"))
    review_before_slack = len(list_items("/mock/slack/messages"))
    review_execution = run_workflow(
        "incident",
        {
            "source": "monitoring",
            "service": f"confidence-demo-{uuid.uuid4().hex[:8]}",
            "severity": "high",
            "events": ["new synthetic latency anomaly without corroborating signals"],
            "fault_profile": "provider_low_confidence",
        },
    )
    require(review_execution["status"] == "waiting_for_review", review_execution)
    require(not review_execution.get("external_actions"), "Low-confidence incident acted before review.")
    approval_id = review_execution["approvals"][0]["id"]
    request_json(
        "POST",
        f"/api/v1/approvals/{approval_id}/approve",
        {"reviewer": "acceptance.operator", "note": "Evidence reviewed for the local demo."},
    )
    approved = request_json("GET", f"/api/v1/executions/{review_execution['execution_id']}")
    require(approved["status"] == "completed", approved)
    require(len(list_items("/mock/jira/issues")) == review_before_jira + 1, "Approval did not create one Jira issue.")
    require(len(list_items("/mock/slack/messages")) == review_before_slack + 1, "Approval did not create one Slack message.")
    assert_n8n_audit(approved, "n8n.incident.waiting_for_review")
    print_result("incident-low-confidence-approved", approved)

    failure_before = len(list_items("/mock/jira/issues"))
    failure_execution = run_workflow(
        "incident",
        {
            "source": "monitoring",
            "service": f"jira-failure-demo-{uuid.uuid4().hex[:8]}",
            "severity": "critical",
            "events": ["new synthetic HTTP 5xx spike"],
            "fault_profile": "jira_failure",
        },
    )
    require(failure_execution["status"] == "failed", f"Jira failure was hidden: {failure_execution}")
    require("jira" in deep_text(failure_execution.get("error")), failure_execution)
    require(len(list_items("/mock/jira/issues")) == failure_before, "Failed Jira request created an issue.")
    require(
        any(not action.get("success", True) for action in failure_execution.get("external_actions", [])),
        f"Failed Jira attempt is absent: {failure_execution}",
    )
    assert_n8n_audit(failure_execution, "n8n.incident.failed")
    print_result("incident-jira-failure", failure_execution)

    print("PASS incident: creation, safe summaries, dedup, review approval, and terminal failure")


if __name__ == "__main__":
    main()
