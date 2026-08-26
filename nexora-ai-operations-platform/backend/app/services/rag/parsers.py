from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

from app.services.rag.chunking import ParsedPage


class DocumentParseError(ValueError):
    pass


def parse_document(
    filename: str,
    content: bytes,
    *,
    max_chars: int | None = None,
) -> list[ParsedPage]:
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
        return [ParsedPage(text=text)]
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
        if not any(page.text.strip() for page in pages):
            raise DocumentParseError("PDF contains no extractable text")
        return pages
    raise DocumentParseError("unsupported file type")
