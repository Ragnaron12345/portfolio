from __future__ import annotations

import pytest

from app.services.ai import MockProvider


def run(client, scenario: str):
    response = client.post(f"/api/v1/demo/scenarios/{scenario}/run")
    assert response.status_code == 200, response.text
    return response.json()


def test_low_risk_support_is_grounded_and_completed(client):
    data = run(client, "support-card-replacement")
    assert data["status"] == "completed"
    decision = data["decision_summary"]
    assert decision["classification"]["category"] == "general_question"
    assert decision["classification"]["risk_level"] == "low"
    assert len(decision["classification"]["reason"]) >= 20
    assert decision["sources"]
    assert all(
        source["title"] and source["excerpt"] and source["relevance_score"] > 0
        for source in decision["sources"]
    )
    assert "5–7 business days" in decision["draft"]
    assert any(action["system"] == "crm" and action["success"] for action in data["external_actions"])


def test_exact_stolen_card_case_requires_review_without_side_effect(client):
    before = client.get("/mock/crm/tickets").json()["total"]
    data = run(client, "support-stolen-card")
    assert data["status"] == "waiting_for_review"
    classification = data["decision_summary"]["classification"]
    assert classification["category"] == "suspected_fraud"
    assert classification["risk_level"] == "high"
    assert "stolen" in classification["reason"].lower()
    assert "security" in classification["reason"].lower()
    draft = data["decision_summary"]["draft"].lower()
    assert "freeze" in draft or "block" in draft
    assert "escalat" in draft or "fraud specialist" in draft
    assert data["approvals"][0]["status"] == "pending"
    assert client.get("/mock/crm/tickets").json()["total"] == before


def test_prompt_injection_is_audited_and_side_effect_is_blocked(client):
    data = run(client, "support-prompt-injection")
    assert data["status"] == "waiting_for_review"
    classification = data["decision_summary"]["classification"]
    assert classification["prompt_injection_detected"] is True
    assert classification["risk_level"] == "high"
    assert any(event["action"] == "prompt_injection_blocked" for event in data["audit_events"])
    assert data["external_actions"] == []


def test_medium_risk_support_routes_to_review(client):
    data = run(client, "support-payment-failed")
    assert data["status"] == "waiting_for_review"
    assert data["decision_summary"]["classification"]["risk_level"] == "medium"


def test_unsupported_support_has_no_external_action(client):
    data = run(client, "support-unsupported")
    assert data["status"] == "completed_with_warning"
    assert data["external_actions"] == []


def test_reject_keeps_side_effect_blocked(client):
    execution = run(client, "support-stolen-card")
    approval_id = execution["approvals"][0]["id"]
    response = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"reviewer": "qa.operator", "note": "Identity could not be verified."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "cancelled"
    assert final["decision_summary"]["side_effect_executed"] is False
    assert final["external_actions"] == []


def test_approved_stolen_card_only_creates_internal_escalation(client):
    execution = run(client, "support-stolen-card")
    approval_id = execution["approvals"][0]["id"]
    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewer": "fraud.operator", "note": "Verified; escalate to fraud operations."},
    )
    assert response.status_code == 200, response.text
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "completed"
    tickets = client.get("/mock/crm/tickets").json()["items"]
    ticket = next(item for item in tickets if item["execution_id"] == execution["id"])
    assert ticket["action"] == "escalation"
    crm_event = next(event for event in final["events"] if event["stage"] == "CRM_UPDATED")
    assert crm_event["details"]["customer_facing"] is False


def test_retry_is_visible_without_raw_provider_output(client):
    data = run(client, "provider-timeout-fallback")
    assert data["status"] == "completed"
    retries = [event for event in data["events"] if event["event_type"] == "provider_retry"]
    assert retries
    assert all(event["details"]["raw_output_exposed"] is False for event in retries)
    assert any(not call["success"] for call in data["ai_calls"])
    assert any(call["success"] for call in data["ai_calls"])


@pytest.mark.parametrize(
    "provider_override,failed_check",
    [
        ({"grounded": False}, "provider_declared_grounded"),
        ({"grounded": True, "source_ids": ["fabricated-policy"]}, "source_ids_retrieved"),
    ],
)
def test_ungrounded_provider_output_never_creates_crm_side_effect(
    client, monkeypatch, provider_override, failed_check
):
    original_complete = MockProvider.complete

    def ungrounded_complete(self, purpose, payload, attempt, fault):
        result = original_complete(self, purpose, payload, attempt, fault)
        if purpose == "support_response":
            return {**result, **provider_override}
        return result

    monkeypatch.setattr(MockProvider, "complete", ungrounded_complete)
    before = client.get("/mock/crm/tickets").json()["total"]

    data = run(client, "support-card-replacement")

    assert data["status"] == "waiting_for_review"
    assert data["decision_summary"]["draft_validation"]["valid"] is False
    assert data["decision_summary"]["draft_validation"]["checks"][failed_check] is False
    assert data["external_actions"] == []
    assert client.get("/mock/crm/tickets").json()["total"] == before


def test_approved_support_adapter_failure_preserves_decision_attempt_and_exact_error(client):
    before = client.get("/mock/crm/tickets").json()["total"]
    run_response = client.post(
        "/api/v1/runs/support",
        json={
            "ticket_id": "T-APPROVED-CRM-FAIL",
            "customer_id": "CUST-APPROVED-FAIL",
            "subject": "Replacement timing",
            "message": "How long does card replacement take?",
            "force_review": True,
            "fault_profile": "crm_failure",
        },
    )
    assert run_response.status_code == 200, run_response.text
    execution = run_response.json()
    assert execution["status"] == "waiting_for_review"
    approval_id = execution["approvals"][0]["id"]

    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewer": "support.operator", "note": "Reviewed and approved."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "failed"
    assert final["error"] == {
        "code": "crm_unavailable",
        "message": "CRM mock rejected the action after the configured bounded attempt.",
        "retryable": False,
    }
    assert final["decision_summary"]["review_status"] == "approved"
    assert final["decision_summary"]["side_effect_executed"] is False
    assert final["approvals"][0]["status"] == "approved"
    assert final["approvals"][0]["decisions"][0]["decision"] == "approved"
    assert [(item["system"], item["success"]) for item in final["external_actions"]] == [("crm", False)]
    assert any(item["action"] == "approved_side_effect_failed" for item in final["audit_events"])
    assert any(item["action"] == "execution_failed" for item in final["audit_events"])
    assert client.get("/mock/crm/tickets").json()["total"] == before
    assert (
        client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reviewer": "support.operator", "note": "Do not run twice."},
        ).status_code
        == 409
    )
