from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

from app.services.rag.chunking import ParsedPage
from app.services.rag.document_ai import DocumentType, route_document_analysis
from app.services.rag.ocr import OcrPage, OcrResult, ocr_document


class DocumentParseError(ValueError):
    pass


def parse_document(
    filename: str,
    content: bytes,
    *,
    max_chars: int | None = None,
) -> list[ParsedPage]:
    pages, _ = parse_document_with_analysis(filename, content, max_chars=max_chars)
    return pages


def parse_document_with_analysis(
    filename: str,
    content: bytes,
    *,
    document_type: DocumentType = "auto",
    max_chars: int | None = None,
) -> tuple[list[ParsedPage], dict[str, object]]:
    extension = Path(filename).suffix.casefold()
    if extension in {".txt", ".md"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("text documents must be UTF-8 encoded") from exc
        if max_chars is not None and len(text) > max_chars:
            raise DocumentParseError("document decoded-text limit exceeded")
        if not text.strip():
            raise DocumentParseError("document is empty")
        pages = [ParsedPage(text=text)]
        result = OcrResult(pages=[OcrPage(text=text, page_number=1)], confidence=1.0, engine="utf-8")
        return pages, route_document_analysis(
            result,
            extraction_method="native_text",
            requested_type=document_type,
        )
    if extension == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            if len(reader.pages) > 500:
                raise DocumentParseError("PDF page limit exceeded")
            pages: list[ParsedPage] = []
            extracted_chars = 0
            for index, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                extracted_chars += len(text)
                if max_chars is not None and extracted_chars > max_chars:
                    raise DocumentParseError("document decoded-text limit exceeded")
                pages.append(ParsedPage(text=text, page_number=index + 1))
        except DocumentParseError:
            raise
        except Exception as exc:  # pypdf uses several parser-specific exception types
            raise DocumentParseError("invalid or unsupported PDF") from exc
        if any(page.text.strip() for page in pages):
            result = OcrResult(
                pages=[
                    OcrPage(text=page.text, page_number=page.page_number or index + 1)
                    for index, page in enumerate(pages)
                ],
                confidence=1.0,
                engine="pypdf",
            )
            return pages, route_document_analysis(
                result,
                extraction_method="native_pdf_text",
                requested_type=document_type,
            )
        return _ocr_pages(filename, content, document_type=document_type, max_chars=max_chars)
    if extension in {".png", ".jpg", ".jpeg"}:
        return _ocr_pages(filename, content, document_type=document_type, max_chars=max_chars)
    raise DocumentParseError("unsupported file type")


def _ocr_pages(
    filename: str,
    content: bytes,
    *,
    document_type: DocumentType,
    max_chars: int | None,
) -> tuple[list[ParsedPage], dict[str, object]]:
    try:
        result = ocr_document(filename, content)
    except (RuntimeError, ValueError) as exc:
        raise DocumentParseError(str(exc)) from exc
    pages = [ParsedPage(text=page.text, page_number=page.page_number) for page in result.pages]
    text_length = sum(len(page.text) for page in pages)
    if max_chars is not None and text_length > max_chars:
        raise DocumentParseError("document decoded-text limit exceeded")
    if not any(page.text.strip() for page in pages):
        raise DocumentParseError("OCR produced no readable text")
    return pages, route_document_analysis(
        result,
        extraction_method="ocr",
        requested_type=document_type,
    )


