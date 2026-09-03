from pathlib import Path

import pytest

from app.config import get_settings
from app.seed import load_jsonl


def test_checked_in_dataset_parses_and_covers_required_categories() -> None:
    path = get_settings().resolved_dataset_path()
    cases, digest = load_jsonl(path)
    assert len(cases) >= 50
    assert len(digest) == 64
    assert {case["metadata"]["category"] for case in cases} == {
        "factual_qa",
        "missing_information",
        "grounded_qa",
        "summarization",
        "extraction",
        "structured_output",
        "adversarial",
    }


def test_dataset_parser_rejects_missing_fields(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text('{"id":"case_1","input":"missing the contract"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_jsonl(invalid)


def test_dataset_parser_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    row = (
        '{"id":"case_1","input":"q","reference_answer":null,'
        '"expected_keywords":[],"forbidden_claims":[],"context":[],'
        '"expected_citations":[],"metadata":{}}'
    )
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(f"{row}\n{row}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_jsonl(duplicate)
