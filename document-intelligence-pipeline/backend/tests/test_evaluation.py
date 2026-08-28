from __future__ import annotations

import json

from app.services.evaluation import run_evaluation


def test_evaluation_uses_ground_truth_and_delta_direction(db, settings, tmp_path) -> None:  # noqa: ANN001
    documents = []
    for index in range(60):
        document_type = ["invoice", "bank_statement", "customer_application"][index // 20]
        documents.append(
            {
                "id": f"CASE-{index:03d}",
                "document_type": document_type,
                "required_field_count": 4,
                "field_count": 7,
                "numeric_field_count": 2,
                "needs_review": index % 5 == 0,
                "edge_cases": ["rotation"] if index % 6 == 0 else [],
            }
        )
    path = tmp_path / "ground_truth.json"
    path.write_text(json.dumps({"documents": documents}), encoding="utf-8")
    settings.ground_truth_path = str(path)
    run = run_evaluation(db, settings, "Test comparison")
    metrics = {item["key"]: item for item in run.metrics_json}
    assert run.dataset_size == 60
    assert metrics["classification_accuracy"]["improvement"] >= 0
    assert metrics["average_latency_ms"]["higher_is_better"] is False
    assert metrics["average_latency_ms"]["improvement"] > 0
