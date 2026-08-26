from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OcrPage:
    text: str
    page_number: int


@dataclass(frozen=True, slots=True)
class OcrResult:
    pages: list[OcrPage]
    confidence: float
    engine: str = "tesseract"


def ocr_document(filename: str, content: bytes, *, max_pages: int = 500) -> OcrResult:
    """OCR an image or scanned PDF with a local, non-networked engine."""

    try:
        import pypdfium2 as pdfium
        import pytesseract
        from PIL import Image
        from pytesseract import Output
    except ImportError as exc:  # pragma: no cover - exercised by deployment checks
        raise RuntimeError("OCR runtime is unavailable; install Pillow, pypdfium2, pytesseract, and Tesseract") from exc

    extension = filename.casefold().rsplit(".", 1)[-1]
    images: list[Any]
    if extension == "pdf":
        document = pdfium.PdfDocument(content)
        if len(document) > max_pages:
            raise ValueError("PDF page limit exceeded")
        images = [document[index].render(scale=2).to_pil() for index in range(len(document))]
    else:
        images = [Image.open(io.BytesIO(content)).convert("RGB")]

    pages: list[OcrPage] = []
    confidences: list[float] = []
    for page_number, image in enumerate(images, start=1):
        data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
        words: list[str] = []
        for raw_text, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
            text = str(raw_text).strip()
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                confidence = -1
            if text:
                words.append(text)
            if confidence >= 0:
                confidences.append(confidence / 100)
        pages.append(OcrPage(text=" ".join(words), page_number=page_number))
    return OcrResult(
        pages=pages,
        confidence=round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
    )


def analyze_business_document(result: OcrResult) -> dict[str, Any]:
    """Extract and validate a deliberately narrow invoice entity schema."""

    text = "\n".join(page.text for page in result.pages)
    normalized = " ".join(text.split())
    invoice_number = _match(
        r"(?i)\b(?:invoice|inv)[\s#:.-]*(?:no\.?|number|id)?[\s#:.-]*([A-Z0-9][A-Z0-9/-]{2,})",
        normalized,
    )
    invoice_date = _match(
        r"(?i)\b(?:invoice\s+date|date)\s*[:.-]?\s*(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})",
        normalized,
    )
    total_match = re.search(
        r"(?i)\b(?:grand\s+total|amount\s+due|total)\s*[:.-]?\s*"
        r"(?:(EUR|USD|GBP|€|\$|£)\s*)?([0-9][0-9., ]*)\s*(EUR|USD|GBP|€|\$|£)?",
        normalized,
    )
    total = _decimal(total_match.group(2)) if total_match else None
    currency = _currency((total_match.group(1) or total_match.group(3)) if total_match else None)
    entities: dict[str, Any] = {
        "document_type": "invoice",
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "currency": currency,
        "total": total,
    }
    required = ("invoice_number", "invoice_date", "currency", "total")
    errors = [f"missing_{field}" for field in required if entities[field] in (None, "")]
    if total is not None and total <= 0:
        errors.append("total_must_be_positive")
    completeness = sum(entities[field] not in (None, "") for field in required) / len(required)
    confidence = round(0.65 * result.confidence + 0.35 * completeness, 4)
    requires_review = bool(errors) or confidence < 0.85
    return {
        "extraction_method": "ocr",
        "ocr_engine": result.engine,
        "ocr_confidence": result.confidence,
        "entity_confidence": confidence,
        "entities": entities,
        "validation": {"valid": not errors, "errors": errors},
        "requires_human_review": requires_review,
        "review_reason": "low OCR/entity confidence or failed field validation" if requires_review else None,
    }


def _match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _decimal(value: str) -> float | None:
    compact = value.replace(" ", "")
    if compact.count(",") == 1 and ("." not in compact or compact.rfind(",") > compact.rfind(".")):
        compact = compact.replace(".", "").replace(",", ".")
    else:
        compact = compact.replace(",", "")
    try:
        return round(float(compact), 2)
    except ValueError:
        return None


def _currency(value: str | None) -> str | None:
    return {"€": "EUR", "$": "USD", "£": "GBP"}.get(value or "", value.upper() if value else None)


