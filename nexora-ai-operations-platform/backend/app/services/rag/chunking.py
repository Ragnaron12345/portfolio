from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedPage:
    text: str
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class TextChunk:
    content: str
    chunk_index: int
    page_number: int | None = None
    char_start: int = 0
    char_end: int = 0


def chunk_pages(
    pages: list[ParsedPage],
    *,
    chunk_size: int = 900,
    overlap: int = 140,
) -> list[TextChunk]:
    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 characters")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    chunks: list[TextChunk] = []
    for page in pages:
        text = _normalize_text(page.text)
        if not text:
            continue
        start = 0
        while start < len(text):
            hard_end = min(len(text), start + chunk_size)
            end = hard_end
            if hard_end < len(text):
                boundary = _best_boundary(text, start, hard_end)
                if boundary > start + chunk_size // 2:
                    end = boundary
            content = text[start:end].strip()
            if content:
                chunks.append(
                    TextChunk(
                        content=content,
                        chunk_index=len(chunks),
                        page_number=page.page_number,
                        char_start=start,
                        char_end=end,
                    )
                )
            if end >= len(text):
                break
            next_start = max(start + 1, end - overlap)
            # Avoid beginning halfway through a word.
            whitespace = text.find(" ", next_start, min(len(text), next_start + 40))
            start = whitespace + 1 if whitespace != -1 else next_start
    return chunks


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _best_boundary(text: str, start: int, hard_end: int) -> int:
    window_start = max(start, hard_end - 180)
    window = text[window_start:hard_end]
    candidates = [window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"), window.rfind(" ")]
    best = max(candidates)
    return window_start + best + (1 if best >= 0 else 0) if best >= 0 else hard_end
