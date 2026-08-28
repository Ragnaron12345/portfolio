from __future__ import annotations

from app.services.confidence import score_confidence
from app.services.validation import validate_extraction


def test_invoice_arithmetic_reports_exact_difference() -> None:
    data = {
        "invoice_number": "INV-7",
        "invoice_date": "2026-05-12",
        "seller_name": "Bluewater",
        "currency": "EUR",
        "subtotal": 1200.0,
        "tax": 228.0,
        "total": 1470.0,
        "line_items": [{"total": 1200.0}],
    }
    rules = validate_extraction("invoice", data)
    arithmetic = next(rule for rule in rules if rule["rule_id"] == "invoice.arithmetic")
    assert arithmetic["status"] == "fail"
    assert arithmetic["details"]["difference"] == 42.0
    assert "42.00 EUR" in arithmetic["message"]


def test_statement_validation_detects_period_and_balance_issues() -> None:
    rules = validate_extraction(
        "bank_statement",
        {
            "period_start": "2026-05-01",
            "period_end": "2026-04-01",
            "opening_balance": 100,
            "closing_balance": 150,
            "transactions": [{"date": "2026-04-15", "amount": 10}],
        },
    )
    assert {rule["rule_id"] for rule in rules if rule["status"] == "fail"} == {
        "statement.period_order",
        "statement.balance_consistency",
    }


def test_confidence_breakdown_is_explainable() -> None:
    score, breakdown = score_confidence(
        "invoice",
        [{"ocr_quality": 0.9, "character_count": 400}],
        0.92,
        {
            "invoice_number": "1",
            "invoice_date": "2026-01-01",
            "seller_name": "Seller",
            "currency": "EUR",
            "subtotal": 10,
            "tax": 2,
            "total": 12,
        },
        [{"status": "pass"}],
        structured_success=True,
    )
    assert 0.8 < score <= 1
    assert set(breakdown["components"]) == {
        "text_quality",
        "classification",
        "schema_validity",
        "required_field_completeness",
        "business_rule_validation",
        "structured_output_success",
    }
    assert sum(breakdown["weights"].values()) == 1
