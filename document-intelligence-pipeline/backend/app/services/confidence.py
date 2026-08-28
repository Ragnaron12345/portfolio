from __future__ import annotations

from typing import Any

REQUIRED_FIELDS = {
    "invoice": ("invoice_number", "invoice_date", "seller_name", "currency", "subtotal", "tax", "total"),
    "bank_statement": (
        "account_holder",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
        "currency",
    ),
    "customer_application": ("full_name",),
}


def score_confidence(
    document_type: str,
    pages: list[dict[str, Any]],
    classification_confidence: float,
    structured_data: dict[str, Any] | None,
    validation_rules: list[dict[str, Any]],
    *,
    structured_success: bool,
) -> tuple[float, dict[str, Any]]:
    if pages:
        page_quality = [
            float(page.get("ocr_quality"))
            if page.get("ocr_quality") is not None
            else min(1.0, float(page.get("character_count", 0)) / 500)
            for page in pages
        ]
        text_quality = sum(page_quality) / len(page_quality)
    else:
        text_quality = 0.0
    required = REQUIRED_FIELDS.get(document_type, ())
    present = sum((structured_data or {}).get(field) not in (None, "") for field in required)
    completeness = present / len(required) if required else 0.0
    schema_validity = 1.0 if structured_success else 0.0
    scored_rules = [item for item in validation_rules if item["status"] != "not_applicable"]
    rule_values = {"pass": 1.0, "warning": 0.55, "fail": 0.0}
    validation_score = (
        sum(rule_values.get(item["status"], 0) for item in scored_rules) / len(scored_rules) if scored_rules else 0.0
    )
    components = {
        "text_quality": round(text_quality, 4),
        "classification": round(classification_confidence, 4),
        "schema_validity": schema_validity,
        "required_field_completeness": round(completeness, 4),
        "business_rule_validation": round(validation_score, 4),
        "structured_output_success": 1.0 if structured_success else 0.0,
    }
    weights = {
        "text_quality": 0.18,
        "classification": 0.18,
        "schema_validity": 0.16,
        "required_field_completeness": 0.18,
        "business_rule_validation": 0.18,
        "structured_output_success": 0.12,
    }
    overall = round(sum(components[key] * weights[key] for key in weights), 4)
    return overall, {
        "definition": "Workflow heuristic combining text quality, classification, schema, completeness, and rules.",
        "components": components,
        "weights": weights,
    }
