from __future__ import annotations

import re
from datetime import date
from typing import Any

SUPPORTED_CURRENCIES = {"EUR", "USD", "GBP", "CHF", "CAD", "AUD", "JPY"}


def rule(rule_id: str, name: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    return {"rule_id": rule_id, "name": name, "status": status, "message": message, "details": details}


def validate_extraction(document_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    if document_type == "invoice":
        return _invoice_rules(data)
    if document_type == "bank_statement":
        return _statement_rules(data)
    if document_type == "customer_application":
        return _application_rules(data)
    return [
        rule("unsupported_type", "Supported document type", "fail", "No deterministic schema exists for this type.")
    ]


def _invoice_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    required = ("invoice_number", "invoice_date", "seller_name", "currency", "subtotal", "tax", "total")
    missing = [field for field in required if data.get(field) in (None, "")]
    results = [
        rule(
            "invoice.required_fields",
            "Required fields",
            "pass" if not missing else "fail",
            "All required invoice fields are present." if not missing else f"Missing: {', '.join(missing)}.",
            missing=missing,
        )
    ]
    subtotal, tax, total = (float(data.get(key) or 0) for key in ("subtotal", "tax", "total"))
    expected_total = round(subtotal + tax, 2)
    difference = round(total - expected_total, 2)
    results.append(
        rule(
            "invoice.arithmetic",
            "Invoice arithmetic",
            "pass" if abs(difference) <= 0.02 else "fail",
            "Subtotal + tax matches total."
            if abs(difference) <= 0.02
            else f"Invoice total differs from subtotal + tax by {abs(difference):.2f} {data.get('currency', '')}.",
            expected=expected_total,
            actual=total,
            difference=difference,
        )
    )
    line_sum = round(sum(float(item.get("total") or 0) for item in data.get("line_items", [])), 2)
    results.append(
        rule(
            "invoice.line_item_sum",
            "Line-item sum",
            "not_applicable"
            if not data.get("line_items")
            else ("pass" if abs(line_sum - subtotal) <= 0.02 else "fail"),
            "No line items were present."
            if not data.get("line_items")
            else (
                "Line items match subtotal."
                if abs(line_sum - subtotal) <= 0.02
                else "Line items do not match subtotal."
            ),
            expected=subtotal,
            actual=line_sum,
        )
    )
    currency = str(data.get("currency") or "").upper()
    results.append(
        rule(
            "currency.recognized",
            "Recognized currency",
            "pass" if currency in SUPPORTED_CURRENCIES else "warning",
            f"{currency} is supported."
            if currency in SUPPORTED_CURRENCIES
            else f"{currency or 'Missing currency'} needs review.",
        )
    )
    return results


def _statement_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    start = date.fromisoformat(str(data["period_start"]))
    end = date.fromisoformat(str(data["period_end"]))
    period_ok = start <= end
    transactions = data.get("transactions", [])
    outside = [item for item in transactions if not start <= date.fromisoformat(str(item["date"])) <= end]
    opening = float(data.get("opening_balance") or 0)
    closing = float(data.get("closing_balance") or 0)
    expected = round(opening + sum(float(item.get("amount") or 0) for item in transactions), 2)
    balance_ok = abs(expected - closing) <= 0.02
    return [
        rule(
            "statement.period_order",
            "Statement period",
            "pass" if period_ok else "fail",
            "Period start is before period end." if period_ok else "Period start occurs after period end.",
        ),
        rule(
            "statement.transaction_dates",
            "Transaction dates",
            "pass" if not outside else "warning",
            "All transaction dates are inside the statement period."
            if not outside
            else f"{len(outside)} transaction date(s) fall outside the period.",
            outside_count=len(outside),
        ),
        rule(
            "statement.balance_consistency",
            "Balance consistency",
            "pass" if balance_ok else "fail",
            "Opening balance plus transactions equals closing balance."
            if balance_ok
            else "Opening balance plus transactions does not equal closing balance.",
            expected=expected,
            actual=closing,
        ),
    ]


def _application_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    full_name = str(data.get("full_name") or "").strip()
    email = str(data.get("email") or "").strip()
    phone = str(data.get("phone") or "").strip()
    email_ok = not email or bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email))
    digits = "".join(character for character in phone if character.isdigit())
    phone_ok = not phone or 7 <= len(digits) <= 15
    if phone:
        data["phone"] = "+" + digits
    return [
        rule(
            "application.full_name",
            "Applicant name",
            "pass" if len(full_name.split()) >= 2 else "fail",
            "Applicant full name is present."
            if len(full_name.split()) >= 2
            else "A complete applicant name is required.",
        ),
        rule(
            "application.email",
            "Email format",
            "not_applicable" if not email else ("pass" if email_ok else "fail"),
            "Email was not supplied."
            if not email
            else ("Email format is valid." if email_ok else "Email format is invalid."),
        ),
        rule(
            "application.phone",
            "Phone normalization",
            "not_applicable" if not phone else ("pass" if phone_ok else "warning"),
            "Phone was not supplied."
            if not phone
            else (f"Phone normalized to +{digits}." if phone_ok else "Phone length is outside the supported range."),
        ),
    ]
