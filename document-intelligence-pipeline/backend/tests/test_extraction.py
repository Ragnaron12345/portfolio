from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.extraction import StaticOCRProvider, extract_document, sniff_file


def test_file_validation_rejects_extension_content_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        sniff_file("invoice.pdf", "application/pdf", b"not-a-pdf")


def test_image_uses_ocr_adapter(tmp_path, settings) -> None:  # noqa: ANN001
    path = tmp_path / "scan.png"
    image = Image.new("RGB", (800, 600), "white")
    image.save(path)
    pages = extract_document(path, settings, ocr_provider=StaticOCRProvider("INVOICE\nTotal: 12.00"))
    assert pages[0].extraction_method == "ocr"
    assert pages[0].ocr_quality == 0.91
    assert "INVOICE" in pages[0].text


def test_native_pdf_extraction_when_pymupdf_available(tmp_path, settings) -> None:  # noqa: ANN001
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "native.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "INVOICE Invoice Number: INV-1 Subtotal: 10 Tax: 2 Total: 12")
    document.save(path)
    document.close()
    pages = extract_document(path, settings, ocr_provider=StaticOCRProvider("unused"))
    assert pages[0].extraction_method == "native"
    assert pages[0].character_count > 32


def test_image_pixel_bomb_is_rejected(tmp_path, settings) -> None:  # noqa: ANN001
    settings.max_image_pixels = 100
    path = tmp_path / "large.png"
    image = Image.new("RGB", (20, 20), "white")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    path.write_bytes(buffer.getvalue())
    with pytest.raises(ValueError, match="pixel limit"):
        extract_document(path, settings, ocr_provider=StaticOCRProvider("text"))
