from __future__ import annotations

import re
from typing import Any, Literal

from app.services.rag.ocr import OcrResult, analyze_business_document

DocumentType = Literal["auto", "general", "invoice"]

_INVOICE_SIGNALS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("invoice_label", re.compile(r"(?i)\binvoice\b"), 2),
    (
        "invoice_number",
        re.compile(
            r"(?i)\b(?:INV[-/][A-Z0-9/-]{2,}|invoice\s*(?:no\.?|number|id|#)\s*[:.-]?\s*[A-Z0-9][A-Z0-9/-]{2,})"
        ),
        2,
    ),
    (
        "invoice_date",
        re.compile(r"(?i)\b(?:invoice\s+date|date)\s*[:.-]?\s*\d{2,4}[-/.]\d{2}[-/.]\d{2,4}"),
        1,
    ),
    (
        "payable_total",
        re.compile(r"(?i)\b(?:grand\s+total|amount\s+due|total)\s*[:.-]?\s*(?:EUR|USD|GBP|€|\$|£)?\s*\d"),
        2,
    ),
    ("currency_amount", re.compile(r"(?i)(?:\b(?:EUR|USD|GBP)\b|€|\$|£)\s*\d+[\d., ]*"), 1),
    ("billing_party", re.compile(r"(?i)\b(?:bill\s+to|sold\s+to|supplier|vendor)\b"), 1),
)


def route_document_analysis(
    result: OcrResult,
    *,
    extraction_method: str,
    requested_type: DocumentType,
) -> dict[str, Any]:
    """Route extracted text before applying a type-specific extraction schema."""

    text = "\n".join(page.text for page in result.pages)
    if requested_type == "auto":
        classification = classify_document_type(text)
        resolved_type = classification["document_type"]
    else:
        resolved_type = requested_type
        classification = {
            "document_type": resolved_type,
            "method": "explicit",
            "score": None,
            "threshold": None,
            "signals": [],
        }
    routing = {
        "requested_type": requested_type,
        "resolved_type": resolved_type,
        "classification": classification,
    }
    if resolved_type == "general":
        return {
            "document_type": "general",
            "extraction_method": extraction_method,
            "extraction_engine": result.engine,
            "extraction_confidence": result.confidence,
            "routing": routing,
            "requires_human_review": False,
        }
    analysis = analyze_business_document(result, extraction_method=extraction_method)
    analysis["document_type"] = "invoice"
    analysis["routing"] = routing
    return analysis


def classify_document_type(text: str) -> dict[str, Any]:
    """Classify invoice-shaped text using multiple deterministic field signals."""

    sample = " ".join(text[:20_000].split())
    matched = [(name, weight) for name, pattern, weight in _INVOICE_SIGNALS if pattern.search(sample)]
    signals = [name for name, _weight in matched]
    score = sum(weight for _name, weight in matched)
    has_financial_value = "payable_total" in signals and "currency_amount" in signals
    has_invoice_identity = "invoice_number" in signals or (
        "invoice_label" in signals and "invoice_date" in signals
    )
    document_type = "invoice" if score >= 6 and has_financial_value and has_invoice_identity else "general"
    return {
        "document_type": document_type,
        "method": "deterministic_invoice_signals_v1",
        "score": score,
        "threshold": 6,
        "signals": signals,
    }
