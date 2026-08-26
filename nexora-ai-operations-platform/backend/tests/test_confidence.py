from app.services.confidence import assess_confidence


def test_confidence_is_transparent_workflow_heuristic() -> None:
    strong = assess_confidence(
        needs_retrieval=True,
        retrieval_score=0.9,
        citation_count=2,
        answer_valid=True,
        tool_required=False,
        tool_success=True,
        structured_output_valid=True,
        self_check_passed=True,
    )
    weak = assess_confidence(
        needs_retrieval=True,
        retrieval_score=0.05,
        citation_count=0,
        answer_valid=True,
        tool_required=True,
        tool_success=False,
        structured_output_valid=False,
        self_check_passed=False,
    )
    assert strong.score > weak.score
    assert strong.components["method"].startswith("weighted workflow decision heuristic")
    assert "weak retrieval evidence" in weak.reasons
    assert "required tool did not complete successfully" in weak.reasons
