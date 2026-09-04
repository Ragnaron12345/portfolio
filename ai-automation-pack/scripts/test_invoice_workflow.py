"""Acceptance probe for deterministic invoice decisions through n8n."""

from __future__ import annotations

import copy
import uuid

from workflow_test_support import (
    assert_n8n_audit,
    deep_text,
    list_items,
    load_case,
    print_result,
    require,
    run_workflow,
)


def unique_payload(case_id: str) -> dict:
    case = load_case("invoice_cases.json", case_id)
    payload = copy.deepcopy(case["input"])
    suffix = uuid.uuid4().hex[:8].upper()
    payload["document_content"] = payload["document_content"].replace("INV-2026-1001", f"INV-DEMO-{suffix}")
    payload["document_content"] = payload["document_content"].replace("INV-2026-1002", f"INV-BAD-{suffix}")
    payload["document_content"] = payload["document_content"].replace("INV-2026-DUP-01", f"INV-DUP-{suffix}")
    return payload


def main() -> None:
    before = len(list_items("/mock/erp/invoices"))
    valid_execution = run_workflow("invoice", unique_payload("invoice-valid"))
    after_valid = len(list_items("/mock/erp/invoices"))
    require(valid_execution["status"] == "completed", f"Valid invoice did not complete: {valid_execution}")
    require(after_valid == before + 1, f"Valid invoice produced {after_valid - before} ERP rows, expected exactly 1.")
    assert_n8n_audit(valid_execution, "n8n.invoice.completed")
    print_result("invoice-valid", valid_execution)

    bad_before = len(list_items("/mock/erp/invoices"))
    bad_execution = run_workflow("invoice", unique_payload("invoice-arithmetic-error"))
    bad_after = len(list_items("/mock/erp/invoices"))
    bad_text = deep_text(bad_execution.get("decision_summary", {}))
    require(bad_execution["status"] == "waiting_for_review", f"Bad total was not reviewed: {bad_execution}")
    require("does not equal" in bad_text, f"Exact arithmetic mismatch is absent: {bad_text}")
    require("1,210.00" in bad_text and "1,000.00" in bad_text and "190.00" in bad_text, bad_text)
    require(bad_after == bad_before, "Arithmetic mismatch reached the ERP mock.")
    assert_n8n_audit(bad_execution, "n8n.invoice.waiting_for_review")
    print_result("invoice-arithmetic-error", bad_execution)

    duplicate_payload = unique_payload("invoice-duplicate")
    duplicate_before = len(list_items("/mock/erp/invoices"))
    first = run_workflow("invoice", duplicate_payload)
    second = run_workflow("invoice", duplicate_payload)
    duplicate_after = len(list_items("/mock/erp/invoices"))
    require(first["status"] == "completed", f"First duplicate fixture did not insert: {first}")
    require(second["status"] == "waiting_for_review", f"Second invoice was not blocked: {second}")
    require("duplicate" in deep_text(second), f"Duplicate reason not visible: {second}")
    require(duplicate_after == duplicate_before + 1, "Duplicate path inserted more than one ERP invoice.")
    assert_n8n_audit(second, "n8n.invoice.waiting_for_review")
    print_result("invoice-duplicate-second", second)

    malformed = load_case("invoice_cases.json", "invoice-malformed-scan")
    malformed_execution = run_workflow("invoice", malformed["input"])
    malformed_decision = malformed_execution.get("decision_summary", {})
    attempts = [call.get("attempt", 0) for call in malformed_execution.get("ai_calls", [])]
    require(malformed_execution["status"] == "waiting_for_review", "Malformed extraction did not enter review.")
    require(max(attempts, default=0) >= 2, f"One repair retry is not visible: {attempts}")
    require(malformed_decision.get("raw_output_exposed") is False, "Raw malformed model output was exposed.")
    assert_n8n_audit(malformed_execution, "n8n.invoice.waiting_for_review")
    print_result(malformed["id"], malformed_execution)

    failure_payload = {
        "document_name": "erp-failure.txt",
        "fault_profile": "erp_failure",
        "extracted_fields": {
            "invoice_number": f"INV-ERP-FAIL-{uuid.uuid4().hex[:8].upper()}",
            "vendor": "Failure Fixture GmbH",
            "invoice_date": "2026-08-25",
            "subtotal": "100.00",
            "tax": "19.00",
            "total": "119.00",
            "currency": "EUR",
            "confidence": 0.99,
        },
    }
    failure_before = len(list_items("/mock/erp/invoices"))
    failure_execution = run_workflow("invoice", failure_payload)
    failure_after = len(list_items("/mock/erp/invoices"))
    require(failure_execution["status"] == "failed", f"ERP failure was hidden: {failure_execution}")
    require("erp" in deep_text(failure_execution.get("error")), failure_execution)
    require(failure_after == failure_before, "Failed ERP request created an invoice.")
    require(
        any(not action.get("success", True) for action in failure_execution.get("external_actions", [])),
        f"Failed ERP attempt is absent: {failure_execution}",
    )
    assert_n8n_audit(failure_execution, "n8n.invoice.failed")
    print_result("invoice-erp-failure", failure_execution)

    print("PASS invoice: valid, arithmetic, duplicate, repair, and terminal-failure paths")


if __name__ == "__main__":
    main()
