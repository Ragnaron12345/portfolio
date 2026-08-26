from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    score: float
    components: dict[str, Any]
    reasons: tuple[str, ...]


def assess_confidence(
    *,
    needs_retrieval: bool,
    retrieval_score: float,
    citation_count: int,
    answer_valid: bool,
    tool_required: bool,
    tool_success: bool,
    structured_output_valid: bool,
    self_check_passed: bool,
) -> ConfidenceAssessment:
    """Return a transparent workflow decision heuristic, not model certainty."""

    retrieval_component = max(0.0, min(1.0, retrieval_score)) if needs_retrieval else 1.0
    citation_component = min(1.0, citation_count / 2) if needs_retrieval else 1.0
    tool_component = float(tool_success) if tool_required else 1.0
    values = {
        "retrieval": retrieval_component,
        "citations": citation_component,
        "answer_validation": float(answer_valid),
        "tool_success": tool_component,
        "structured_output": float(structured_output_valid),
        "self_check": float(self_check_passed),
    }
    weights = {
        "retrieval": 0.25,
        "citations": 0.15,
        "answer_validation": 0.2,
        "tool_success": 0.15,
        "structured_output": 0.1,
        "self_check": 0.15,
    }
    score = round(sum(values[key] * weights[key] for key in weights), 4)
    reasons: list[str] = []
    if needs_retrieval and retrieval_component < 0.15:
        reasons.append("weak retrieval evidence")
    if needs_retrieval and citation_count == 0:
        reasons.append("grounded response has no citations")
    if not answer_valid:
        reasons.append("answer validation failed")
    if tool_required and not tool_success:
        reasons.append("required tool did not complete successfully")
    if not structured_output_valid:
        reasons.append("structured model output was invalid")
    if not self_check_passed:
        reasons.append("grounding self-check failed")
    return ConfidenceAssessment(
        score=score,
        components={
            **{key: round(value, 4) for key, value in values.items()},
            "method": "weighted workflow decision heuristic; not calibrated probability",
            "weights": weights,
            "component_explanations": {
                "retrieval": "Best hybrid retrieval relevance score, or 1 when retrieval is not required.",
                "citations": "Evidence coverage reaches 1 after two valid citations.",
                "answer_validation": "Response is non-empty and inside the configured output limit.",
                "tool_success": "Every required allowlisted tool completed successfully.",
                "structured_output": "Classification satisfied the validated structured contract.",
                "self_check": "Grounded work has retrieved evidence and citations.",
            },
            "formula": "sum(component × weight)",
        },
        reasons=tuple(reasons),
    )
