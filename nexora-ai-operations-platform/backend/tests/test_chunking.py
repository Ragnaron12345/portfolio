import pytest

from app.services.rag.chunking import ParsedPage, chunk_pages
from app.services.rag.parsers import DocumentParseError, parse_document


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
