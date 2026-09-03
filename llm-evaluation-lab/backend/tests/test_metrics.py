import pytest

from app.metrics import (
    calculate_cost,
    delta_value,
    exact_match,
    expected_citation_hit,
    forbidden_claim_rate,
    json_and_schema_validity,
    keyword_recall,
    normalize_text,
    normalized_exact_match,
    recall_at_k,
    render_prompt,
)


def test_exact_match_and_normalization() -> None:
    assert exact_match("Mars.", "Mars.") == 1
    assert exact_match("mars", "Mars.") == 0
    assert normalize_text("  Mars, the RED planet! ") == "mars the red planet"
    assert normalized_exact_match("Mars, the RED planet!", "mars the red planet") == 1
    assert normalized_exact_match("anything", None) is None


def test_keyword_recall_has_accessible_counts() -> None:
    value, numerator, denominator = keyword_recall("Refunds take 30 calendar days.", ["30 calendar days", "purchase"])
    assert value == 0.5
    assert (numerator, denominator) == (1, 2)


def test_forbidden_claim_rate() -> None:
    value, numerator, denominator = forbidden_claim_rate(
        "Approval is guaranteed.", ["approval is guaranteed", "instant payout"]
    )
    assert value == 0.5
    assert (numerator, denominator) == (1, 2)


@pytest.mark.parametrize(
    ("output", "parse_rate", "schema_rate"),
    [
        ('{"answer":"ok","confidence":1}', 1.0, 1.0),
        ('{"answer":"ok"}', 1.0, 0.0),
        ('{"answer":', 0.0, 0.0),
    ],
)
def test_json_parse_and_schema_validity(output: str, parse_rate: float, schema_rate: float) -> None:
    assert json_and_schema_validity(output, ["answer", "confidence"]) == (parse_rate, schema_rate)


def test_cost_calculation_requires_usage_and_pricing() -> None:
    assert calculate_cost(1000, 500, 2, 8) == pytest.approx(0.006)
    assert calculate_cost(None, 500, 2, 8) is None
    assert calculate_cost(1000, 500, None, 8) is None


def test_delta_semantics_for_rates_and_lower_is_better() -> None:
    quality = delta_value("keyword_recall", 0.7, 0.8)
    assert quality == {
        "absolute": pytest.approx(0.1),
        "relative_percent": pytest.approx(14.285714),
        "improved": True,
        "display_unit": "percentage points",
    }
    latency = delta_value("p95_latency", 120, 90)
    assert latency["absolute"] == -30
    assert latency["relative_percent"] == -25
    assert latency["improved"] is True
    assert latency["display_unit"] == "ms"


def test_recall_at_k_and_citation_hit() -> None:
    chunks = [
        {"source_id": "doc_a", "rank": 1},
        {"source_id": "doc_b", "rank": 2},
        {"source_id": "doc_c", "rank": 3},
    ]
    assert recall_at_k(chunks, ["doc_b", "doc_x"], 2) == (0.5, 1, 2)
    assert expected_citation_hit("Answer [doc_b]", ["doc_b", "doc_x"]) == (1.0, 1, 2)


def test_prompt_rendering() -> None:
    rendered = render_prompt("Context:\n{context}\nQuestion: {input}", "What changed?", ["doc_a::Latency fell."])
    assert "Latency fell" in rendered
    assert rendered.endswith("Question: What changed?")
