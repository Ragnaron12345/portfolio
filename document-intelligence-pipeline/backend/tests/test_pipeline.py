from __future__ import annotations

import hashlib

from PIL import Image

from app.models import Document, ReviewItem
from app.services.extraction import StaticOCRProvider
from app.services.pipeline import process_document
from app.services.provider import DeterministicProvider


def make_document(db, tmp_path, text: str) -> Document:  # noqa: ANN001
    path = tmp_path / "invoice.png"
    Image.new("RGB", (800, 600), "white").save(path)
    content = path.read_bytes()
    document = Document(
        filename="invoice.png",
        safe_filename="invoice-test.png",
        mime_type="image/png",
        size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(path),
    )
    db.add(document)
    db.commit()
    return document


def test_clean_invoice_is_auto_accepted(db, tmp_path, settings) -> None:  # noqa: ANN001
    text = """INVOICE
Invoice Number: INV-1
Invoice Date: 2026-05-12
Seller: Bluewater
Buyer: Northwind
Currency: EUR
ITEM | Service | 1 | 100.00 | 100.00
Subtotal: 100.00
Tax: 19.00
Total: 119.00
"""
    document = make_document(db, tmp_path, text)
    result = process_document(
        db,
        document,
        settings,
        provider=DeterministicProvider(),
        ocr_provider=StaticOCRProvider(text, quality=0.98),
    )
    assert result.status == "accepted"
    assert result.stages_json[-1]["name"] == "ACCEPTED"
    assert all(stage["status"] != "failed" for stage in result.stages_json)


def test_incorrect_total_routes_to_review_with_specific_reason(db, tmp_path, settings) -> None:  # noqa: ANN001
    text = """INVOICE
Invoice Number: INV-2
Invoice Date: 2026-05-12
Seller: Bluewater
Buyer: Northwind
Currency: EUR
ITEM | Service | 1 | 100.00 | 100.00
Subtotal: 100.00
Tax: 19.00
Total: 161.00
"""
    document = make_document(db, tmp_path, text)
    result = process_document(
        db,
        document,
        settings,
        provider=DeterministicProvider(),
        ocr_provider=StaticOCRProvider(text, quality=0.98),
    )
    assert result.status == "needs_review"
    assert "42.00 EUR" in (result.review_reason or "")
    review = db.query(ReviewItem).filter_by(document_id=result.id).one()
    assert review.decision_history_json[0]["action"] == "routed_to_review"
