import pytest

from app.services.rag.chunking import ParsedPage, chunk_pages
from app.services.rag.ocr import OcrPage, OcrResult, analyze_business_document
from app.services.rag.parsers import DocumentParseError, parse_document, parse_document_with_analysis


def test_chunking_preserves_page_metadata_and_overlap() -> None:
    text = " ".join(f"token-{index}" for index in range(260))
    chunks = chunk_pages([ParsedPage(text=text, page_number=3)], chunk_size=300, overlap=60)
    assert len(chunks) > 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page_number == 3 for chunk in chunks)
    assert all(len(chunk.content) <= 300 for chunk in chunks)
    assert all(chunk.char_start < chunk.char_end for chunk in chunks)
    assert [chunk.char_start for chunk in chunks] == sorted(chunk.char_start for chunk in chunks)
    assert set(chunks[0].content.split()) & set(chunks[1].content.split())


def test_chunking_normalizes_blank_pages_and_rejects_invalid_configuration() -> None:
    assert chunk_pages([ParsedPage(text="  \n\n ")]) == []
    try:
        chunk_pages([ParsedPage(text="hello")], chunk_size=100, overlap=100)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid overlap was accepted")


def test_parser_enforces_cumulative_decoded_character_limit(monkeypatch) -> None:  # noqa: ANN001
    class FakePage:
        def extract_text(self) -> str:
            return "abcdef"

    class FakeReader:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            self.pages = [FakePage(), FakePage()]

    monkeypatch.setattr("app.services.rag.parsers.PdfReader", FakeReader)
    with pytest.raises(DocumentParseError, match="decoded-text limit"):
        parse_document("bounded.pdf", b"synthetic", max_chars=10)
    with pytest.raises(DocumentParseError, match="decoded-text limit"):
        parse_document("bounded.txt", b"x" * 11, max_chars=10)


def test_scanned_pdf_falls_back_to_ocr_and_extracts_validated_invoice(monkeypatch) -> None:  # noqa: ANN001
    class EmptyPage:
        def extract_text(self) -> str:
            return ""

    class FakeReader:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            self.pages = [EmptyPage()]

    monkeypatch.setattr("app.services.rag.parsers.PdfReader", FakeReader)
    monkeypatch.setattr(
        "app.services.rag.parsers.ocr_document",
        lambda *_args, **_kwargs: OcrResult(
            pages=[OcrPage("Invoice INV-2048 Invoice date: 2026-08-20 Total: EUR 149.90", 1)],
            confidence=0.96,
        ),
    )

    pages, analysis = parse_document_with_analysis("scan.pdf", b"scanned")

    assert pages[0].text.startswith("Invoice INV-2048")
    assert analysis["extraction_method"] == "ocr"
    assert analysis["entities"]["invoice_number"] == "INV-2048"
    assert analysis["entities"]["total"] == 149.9
    assert analysis["validation"]["valid"] is True
    assert analysis["requires_human_review"] is False


def test_native_pdf_uses_common_invoice_analysis(monkeypatch) -> None:  # noqa: ANN001
    class NativePage:
        def extract_text(self) -> str:
            return "Invoice INV-4096 Invoice date: 2026-08-25 Amount due: USD 275.40"

    class FakeReader:
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            self.pages = [NativePage()]

    monkeypatch.setattr("app.services.rag.parsers.PdfReader", FakeReader)

    pages, analysis = parse_document_with_analysis("native-invoice.pdf", b"native-pdf")

    assert pages[0].text.startswith("Invoice INV-4096")
    assert analysis["extraction_method"] == "native_pdf_text"
    assert analysis["extraction_engine"] == "pypdf"
    assert analysis["entities"]["invoice_number"] == "INV-4096"
    assert analysis["entities"]["currency"] == "USD"
    assert analysis["entities"]["total"] == 275.4
    assert analysis["validation"]["valid"] is True
    assert analysis["requires_human_review"] is False


def test_invoice_validation_routes_low_confidence_extraction_to_review() -> None:
    analysis = analyze_business_document(
        OcrResult(pages=[OcrPage("Invoice image with unreadable fields", 1)], confidence=0.42)
    )

    assert analysis["validation"]["valid"] is False
    assert "missing_total" in analysis["validation"]["errors"]
    assert analysis["requires_human_review"] is True


