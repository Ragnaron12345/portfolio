from __future__ import annotations

import pytest

from app.schemas import IncidentSummary
from app.services.workflows import validate_incident_summary


def run(client, scenario: str):
    response = client.post(f"/api/v1/demo/scenarios/{scenario}/run")
    assert response.status_code == 200, response.text
    return response.json()


def test_incident_creates_jira_and_slack_with_hypotheses(client):
    jira_before = client.get("/mock/jira/issues").json()["total"]
    slack_before = client.get("/mock/slack/messages").json()["total"]
    data = run(client, "incident-payment-outage")
    assert data["status"] == "completed"
    summary = data["decision_summary"]["summary"]
    assert summary["observed_symptoms"]
    assert all(cause.lower().startswith(("possible:", "hypothesis:")) for cause in summary["possible_causes"])
    assert "confirmed root cause" not in " ".join(summary["possible_causes"]).lower()
    assert client.get("/mock/jira/issues").json()["total"] == jira_before + 1
    assert client.get("/mock/slack/messages").json()["total"] == slack_before + 1


def test_duplicate_updates_existing_incident_without_new_jira(client):
    before_items = client.get("/mock/jira/issues").json()["items"]
    before_count = len(before_items)
    seed = next(item for item in before_items if item["incident_key"] == "INC-SEED")
    data = run(client, "incident-duplicate-burst")
    after_items = client.get("/mock/jira/issues").json()["items"]
    assert data["status"] == "completed_with_warning"
    assert data["decision_summary"]["reason"].startswith("Deduplicated into INC-SEED")
    assert len(after_items) == before_count
    updated = next(item for item in after_items if item["incident_key"] == "INC-SEED")
    assert updated["occurrences"] == seed["occurrences"] + 1
    assert not any(action["action"] == "create_incident" for action in data["external_actions"])


def test_normalized_event_order_deduplicates(client):
    payload = {
        "source": "monitoring",
        "service": "catalog-api",
        "severity": "high",
        "events": ["HTTP errors", "Latency spike"],
    }
    first = client.post("/api/v1/runs/incident", json=payload).json()
    payload["events"] = ["  latency   spike ", "http ERRORS"]
    second = client.post("/api/v1/runs/incident", json=payload).json()
    assert first["status"] == "completed"
    assert second["status"] == "completed_with_warning"
    assert second["decision_summary"]["incident_key"] == first["decision_summary"]["incident_key"]


def test_slack_first_503_is_retried_once(client):
    response = client.post(
        "/api/v1/runs/incident",
        json={
            "source": "monitoring",
            "service": "retry-api",
            "severity": "high",
            "events": ["HTTP 5xx spike"],
            "fault_profile": "slack_failure_once",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    slack_actions = [action for action in data["external_actions"] if action["system"] == "slack"]
    assert [(item["attempt"], item["success"]) for item in slack_actions] == [(1, False), (2, True)]


def test_low_confidence_incident_waits_for_review_then_creates_side_effects_once(client):
    jira_before = client.get("/mock/jira/issues").json()["total"]
    slack_before = client.get("/mock/slack/messages").json()["total"]

    execution = run(client, "incident-low-confidence")

    assert execution["status"] == "waiting_for_review"
    assert execution["current_stage"] == "REVIEW_CREATED"
    assert execution["decision_summary"]["summary"]["confidence"] == 0.42
    assert execution["decision_summary"]["automatic_external_side_effect"] is False
    assert execution["external_actions"] == []
    assert execution["approvals"][0]["status"] == "pending"
    assert client.get("/mock/jira/issues").json()["total"] == jira_before
    assert client.get("/mock/slack/messages").json()["total"] == slack_before
    assert any(item["action"] == "incident_review_created" for item in execution["audit_events"])

    approval_id = execution["approvals"][0]["id"]
    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewer": "incident.operator", "note": "Evidence reviewed; create incident."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "completed"
    assert final["decision_summary"]["side_effect_executed"] is True
    assert client.get("/mock/jira/issues").json()["total"] == jira_before + 1
    assert client.get("/mock/slack/messages").json()["total"] == slack_before + 1
    assert len([item for item in final["external_actions"] if item["system"] == "jira"]) == 1
    assert len([item for item in final["external_actions"] if item["system"] == "slack"]) == 1


def test_incomplete_scenario_is_strictly_rejected(client):
    response = client.post("/api/v1/demo/scenarios/incident-incomplete/run")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "scenario_validation_error"


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("title", "Root cause is cache corruption"),
        ("observed_symptoms", ["Service is definitely caused by cache corruption"]),
        ("probable_impact", "Confirmed root cause is affecting all customer requests."),
        ("possible_causes", ["Possible: the root cause is cache corruption"]),
        ("suggested_investigation_steps", ["Record that the root cause is cache corruption"]),
    ],
)
def test_incident_summary_rejects_confirmed_root_cause_in_every_text_field(field, unsafe_value):
    summary_data = {
        "title": "High symptoms detected for checkout-api",
        "observed_symptoms": ["HTTP 5xx spike"],
        "probable_impact": "Customer checkout requests may fail during the incident window.",
        "possible_causes": ["Possible: upstream dependency saturation"],
        "suggested_investigation_steps": ["Inspect latency and error dashboards."],
        "confidence": 0.8,
    }
    summary_data[field] = unsafe_value
    summary = IncidentSummary.model_validate(summary_data)

    validation = validate_incident_summary(summary, ["HTTP 5xx spike"])

    assert validation["valid"] is False
    assert validation["checks"]["no_unconfirmed_root_cause"] is False


def _create_incident_approval(client, internal_headers, fault_profile):
    execution_response = client.post(
        "/api/v1/executions",
        json={
            "workflow": "incident",
            "correlation_id": f"corr-approval-{fault_profile}",
            "input_data": {"fault_profile": fault_profile},
        },
    )
    assert execution_response.status_code == 200, execution_response.text
    execution = execution_response.json()
    approval_response = client.post(
        "/api/v1/approvals",
        headers=internal_headers,
        json={
            "execution_id": execution["id"],
            "workflow": "incident",
            "reason": "Low-confidence incident summary requires operator approval.",
            "decision_context": {
                "summary": {
                    "title": "High symptoms detected for approval-safety-api",
                    "observed_symptoms": ["HTTP 5xx spike"],
                    "probable_impact": "Requests may fail during the current incident window.",
                    "possible_causes": ["Possible: upstream dependency instability"],
                    "suggested_investigation_steps": ["Inspect service and dependency health."],
                    "confidence": 0.42,
                },
                "service": "approval-safety-api",
                "severity": "high",
                "fingerprint": f"approval-{fault_profile}",
                "fault_profile": fault_profile,
                "side_effect_allowed": True,
            },
        },
    )
    assert approval_response.status_code == 200, approval_response.text
    return execution, approval_response.json()


@pytest.mark.parametrize(
    ("fault_profile", "error_code", "error_message", "expected_actions", "jira_delta"),
    [
        (
            "jira_failure",
            "jira_unavailable",
            "Jira mock rejected the incident after the configured bounded attempt.",
            [("jira", False)],
            0,
        ),
        (
            "slack_failure",
            "slack_unavailable",
            "Slack mock rejected the notification after the configured bounded attempt.",
            [("jira", True), ("slack", False)],
            1,
        ),
    ],
)
def test_approved_incident_adapter_failure_preserves_decision_attempt_and_exact_error(
    client,
    internal_headers,
    fault_profile,
    error_code,
    error_message,
    expected_actions,
    jira_delta,
):
    jira_before = client.get("/mock/jira/issues").json()["total"]
    slack_before = client.get("/mock/slack/messages").json()["total"]
    execution, approval = _create_incident_approval(client, internal_headers, fault_profile)

    response = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"reviewer": "incident.operator", "note": "Evidence reviewed and approved."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "failed"
    assert final["error"] == {
        "code": error_code,
        "message": error_message,
        "retryable": False,
    }
    assert final["decision_summary"]["review_status"] == "approved"
    assert final["decision_summary"]["failed_system"] == fault_profile.removesuffix("_failure")
    assert final["decision_summary"]["side_effect_executed"] is (jira_delta == 1)
    assert final["approvals"][0]["status"] == "approved"
    assert final["approvals"][0]["decisions"][0]["decision"] == "approved"
    assert [(item["system"], item["success"]) for item in final["external_actions"]] == expected_actions
    assert any(item["action"] == "approved_side_effect_failed" for item in final["audit_events"])
    assert any(item["action"] == "execution_failed" for item in final["audit_events"])
    assert client.get("/mock/jira/issues").json()["total"] == jira_before + jira_delta
    assert client.get("/mock/slack/messages").json()["total"] == slack_before
    assert (
        client.post(
            f"/api/v1/approvals/{approval['id']}/approve",
            json={"reviewer": "incident.operator", "note": "Do not run twice."},
        ).status_code
        == 409
    )
