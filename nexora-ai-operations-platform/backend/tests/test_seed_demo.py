from app.seed_demo import _normalize_evaluation_metadata, _rewrite_citation_sources


def test_seed_citation_source_backfill_is_idempotent() -> None:
    citations = [
        {
            "document_id": "doc-card",
            "chunk_id": "chunk-1",
            "title": "Card Replacement Procedure",
            "source": "card_replacement_procedure.md",
            "chunk_index": 0,
            "excerpt": "Freeze the card.",
            "score": 0.9,
        },
        {
            "document_id": "legacy-without-map",
            "chunk_id": "chunk-2",
            "title": "Fraud Escalation Policy",
            "source": "fraud_escalation_policy.md",
            "chunk_index": 0,
            "excerpt": "Escalate fraud.",
            "score": 0.8,
        },
    ]

    first, first_changes = _rewrite_citation_sources(
        citations,
        {"doc-card": "Operations Manual"},
    )
    assert first_changes == 2
    assert [item["source"] for item in first] == ["Operations Manual", "Risk & Compliance"]

    second, second_changes = _rewrite_citation_sources(
        first,
        {"doc-card": "Operations Manual"},
    )
    assert second == first
    assert second_changes == 0
    # The helper returns new dictionaries instead of mutating persisted JSON in
    # place, which is required for reliable SQLAlchemy change tracking.
    assert first is not citations
    assert first[0] is not citations[0]


def test_seed_evaluation_metadata_backfill_is_truthful_and_idempotent() -> None:
    original = {
        "case_count": 40,
        "dataset": {
            "name": "Nexora synthetic support scenarios",
            "version": "v5",
            "sha256": "dataset-hash",
        },
        "evaluator": {"version": "nexora-evaluator-v2", "sha256": "historical-code-hash"},
    }

    first, first_changed = _normalize_evaluation_metadata(original)
    assert first_changed is True
    assert first["dataset"] == {
        "name": "Fintech support",
        "version": "v1",
        "sha256": "dataset-hash",
        "case_count": 40,
        "source": "repository",
    }
    assert first["evaluator"] == {"version": "v5", "sha256": "historical-code-hash"}

    second, second_changed = _normalize_evaluation_metadata(first)
    assert second == first
    assert second_changed is False
