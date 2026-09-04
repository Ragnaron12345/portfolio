from __future__ import annotations


def run(client, scenario: str):
    response = client.post(f"/api/v1/demo/scenarios/{scenario}/run")
    assert response.status_code == 200, response.text
    return response.json()


def test_valid_invoice_creates_exactly_one_erp_record(client):
    before = client.get("/mock/erp/invoices").json()["total"]
    data = run(client, "invoice-valid")
    after = client.get("/mock/erp/invoices").json()["total"]
    assert data["status"] == "completed"
    assert data["decision_summary"]["validation"]["valid"] is True
    assert after == before + 1
    assert sum(action["system"] == "erp" and action["success"] for action in data["external_actions"]) == 1


def test_arithmetic_mismatch_is_exact_and_blocks_erp(client):
    before = client.get("/mock/erp/invoices").json()["total"]
    data = run(client, "invoice-arithmetic-error")
    assert data["status"] == "waiting_for_review"
    assert data["decision_summary"]["reason"] == (
        "Invoice total €1,210.00 does not equal subtotal €1,000.00 + tax €190.00."
    )
    arithmetic = next(
        check for check in data["decision_summary"]["validation"]["checks"] if check["name"] == "arithmetic"
    )
    assert arithmetic["passed"] is False
    assert client.get("/mock/erp/invoices").json()["total"] == before


def test_duplicate_is_deterministic_and_does_not_insert(client):
    before = client.get("/mock/erp/invoices").json()["total"]
    data = run(client, "invoice-duplicate")
    assert data["status"] == "waiting_for_review"
    assert data["decision_summary"]["duplicate_check"]["duplicate"] is True
    assert "already exists" in data["decision_summary"]["reason"]
    assert client.get("/mock/erp/invoices").json()["total"] == before


def test_repeated_valid_invoice_is_blocked_as_duplicate(client):
    first = run(client, "invoice-valid")
    assert first["status"] == "completed"
    count = client.get("/mock/erp/invoices").json()["total"]
    second = run(client, "invoice-valid")
    assert second["status"] == "waiting_for_review"
    assert second["decision_summary"]["duplicate_check"]["duplicate"] is True
    assert client.get("/mock/erp/invoices").json()["total"] == count


def test_missing_tax_creates_review(client):
    data = run(client, "invoice-missing-tax")
    assert data["status"] == "waiting_for_review"
    assert "Missing required fields: tax" in data["decision_summary"]["reason"]
    assert data["approvals"][0]["decision_context"]["side_effect_allowed"] is False


def test_malformed_extraction_repairs_once_then_hides_raw_output(client):
    data = run(client, "invoice-malformed-scan")
    assert data["status"] == "waiting_for_review"
    assert data["decision_summary"]["raw_output_exposed"] is False
    assert "one bounded repair retry" in data["decision_summary"]["reason"]
    failed_calls = [call for call in data["ai_calls"] if not call["success"]]
    assert len(failed_calls) == 2
    assert {call["error_code"] for call in failed_calls} == {"provider_malformed_output"}


def test_approval_cannot_override_deterministic_mismatch(client):
    execution = run(client, "invoice-arithmetic-error")
    approval_id = execution["approvals"][0]["id"]
    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewer": "finance.operator", "note": "Acknowledged discrepancy."},
    )
    assert response.status_code == 200
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "completed_with_warning"
    assert final["decision_summary"]["side_effect_executed"] is False
    assert not any(action["system"] == "erp" for action in final["external_actions"])


def test_valid_forced_review_approval_creates_exactly_one_erp_record(client):
    before = client.get("/mock/erp/invoices").json()["total"]
    run_response = client.post(
        "/api/v1/runs/invoice",
        json={
            "document_name": "forced-review-valid.txt",
            "force_review": True,
            "extracted_fields": {
                "invoice_number": "INV-FORCED-REVIEW-VALID",
                "vendor": "Reviewed Invoice GmbH",
                "invoice_date": "2026-08-25",
                "subtotal": "200.00",
                "tax": "38.00",
                "total": "238.00",
                "currency": "EUR",
                "confidence": 0.99,
            },
        },
    )
    assert run_response.status_code == 200, run_response.text
    execution = run_response.json()
    assert execution["status"] == "waiting_for_review"
    approval_id = execution["approvals"][0]["id"]

    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewer": "finance.operator", "note": "Invoice verified."},
    )

    assert response.status_code == 200, response.text
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "completed"
    assert final["decision_summary"]["review_status"] == "approved"
    assert final["decision_summary"]["side_effect_executed"] is True
    assert client.get("/mock/erp/invoices").json()["total"] == before + 1
    assert [(item["system"], item["success"]) for item in final["external_actions"]] == [("erp", True)]


def test_decimal_tolerance_endpoint(client, internal_headers):
    payload = {
        "invoice_number": "INV-TOL",
        "vendor": "Tolerance GmbH",
        "invoice_date": "2026-08-20",
        "subtotal": "10.00",
        "tax": "1.00",
        "total": "11.01",
        "currency": "EUR",
        "confidence": 1,
    }
    response = client.post("/api/v1/invoices/validate", headers=internal_headers, json=payload)
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_approved_invoice_adapter_failure_preserves_decision_attempt_and_exact_error(client):
    before = client.get("/mock/erp/invoices").json()["total"]
    run_response = client.post(
        "/api/v1/runs/invoice",
        json={
            "document_name": "approved-erp-failure.txt",
            "force_review": True,
            "fault_profile": "erp_failure",
            "extracted_fields": {
                "invoice_number": "INV-APPROVED-ERP-FAIL",
                "vendor": "Approval Safety GmbH",
                "invoice_date": "2026-08-25",
                "subtotal": "100.00",
                "tax": "19.00",
                "total": "119.00",
                "currency": "EUR",
                "confidence": 0.99,
            },
        },
    )
    assert run_response.status_code == 200, run_response.text
    execution = run_response.json()
    assert execution["status"] == "waiting_for_review"
    assert execution["approvals"][0]["decision_context"]["side_effect_allowed"] is True
    approval_id = execution["approvals"][0]["id"]

    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewer": "finance.operator", "note": "Validated and approved."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    final = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert final["status"] == "failed"
    assert final["error"] == {
        "code": "erp_unavailable",
        "message": "ERP mock rejected the invoice after the configured bounded attempt.",
        "retryable": False,
    }
    assert final["decision_summary"]["review_status"] == "approved"
    assert final["decision_summary"]["side_effect_executed"] is False
    assert final["approvals"][0]["status"] == "approved"
    assert final["approvals"][0]["decisions"][0]["decision"] == "approved"
    assert [(item["system"], item["success"]) for item in final["external_actions"]] == [("erp", False)]
    assert any(item["action"] == "approved_side_effect_failed" for item in final["audit_events"])
    assert client.get("/mock/erp/invoices").json()["total"] == before
