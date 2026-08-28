from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import SessionLocal, create_schema, utcnow
from app.models import Document, EvaluationRun, ReviewItem
from app.services.confidence import score_confidence
from app.services.evaluation import run_evaluation
from app.services.validation import validate_extraction


def seed_demo(*, reset: bool = False) -> None:
    settings = get_settings()
    create_schema()
    if not settings.ground_truth_file.exists():
        return
    payload = json.loads(settings.ground_truth_file.read_text(encoding="utf-8"))
    records = payload["documents"]
    with SessionLocal() as db:
        if reset:
            db.execute(delete(ReviewItem))
            db.execute(delete(Document))
            db.execute(delete(EvaluationRun))
            db.commit()
        if db.scalar(select(func.count(Document.id))) == 0:
            for index, record in enumerate(records):
                _seed_document(db, record, index, settings.ground_truth_file.parent)
            db.commit()
        if db.scalar(select(func.count(EvaluationRun.id))) == 0:
            run_evaluation(db, settings, "Synthetic dataset · Run 0042")


def _seed_document(db, record: dict, index: int, data_root: Path) -> None:  # noqa: ANN001
    data = record.get("ground_truth")
    pages = record.get("pages") or [
        {
            "page_number": 1,
            "extraction_method": "ocr" if "image_only" in record.get("edge_cases", []) else "native",
            "text": record.get("source_text", ""),
            "character_count": len(record.get("source_text", "")),
            "ocr_quality": 0.78 if "low_contrast" in record.get("edge_cases", []) else 0.94,
            "latency_ms": 480 + index * 11,
        }
    ]
    rules = validate_extraction(record["document_type"], data) if data else []
    score, breakdown = score_confidence(
        record["document_type"], pages, 0.92 if data else 0.38, data, rules, structured_success=bool(data)
    )
    has_problem = record.get("needs_review", False) or record["document_type"] == "unknown"
    status = (
        "failed" if "empty_page" in record.get("edge_cases", []) else ("needs_review" if has_problem else "accepted")
    )
    reason = record.get("review_reason") if status == "needs_review" else None
    # Ground-truth files are generated on the host and therefore contain host
    # paths. Rebuild the path from the mounted dataset root so seeding remains
    # portable in Docker and on another developer machine.
    path = (data_root / "synthetic_documents" / record["document_type"] / record["filename"]).resolve()
    doc = Document(
        filename=record["filename"],
        safe_filename=f"seed-{index:03d}{Path(record['filename']).suffix}",
        mime_type=record["mime_type"],
        size_bytes=path.stat().st_size if path.exists() else 0,
        checksum_sha256=record["sha256"],
        storage_path=str(path),
        status=status,
        document_type=record["document_type"],
        classification_confidence=0.92 if data else 0.38,
        classification_reason=record.get("classification_reason", "Matched supported structural signals."),
        extracted_text=record.get("source_text", ""),
        pages_json=pages,
        structured_json=data,
        validation_json=rules,
        confidence_score=score,
        confidence_json=breakdown,
        review_reason=reason,
        provider="mock",
        model="deterministic-v1",
        total_latency_ms=round(sum(page["latency_ms"] for page in pages) + 430 + index * 7, 2),
        stages_json=_stages(record, pages, rules, score, status, reason),
        error="OCR produced no readable text." if status == "failed" else None,
        completed_at=utcnow(),
    )
    db.add(doc)
    db.flush()
    if status == "needs_review":
        db.add(
            ReviewItem(
                document_id=doc.id,
                reason=reason or "Confidence or validation gate requires review.",
                decision_history_json=[
                    {
                        "action": "routed_to_review",
                        "actor": "pipeline",
                        "reason": reason,
                        "created_at": utcnow().isoformat(),
                    }
                ],
            )
        )


def _stages(
    record: dict, pages: list[dict], rules: list[dict], score: float, status: str, reason: str | None
) -> list[dict]:
    warning = any(item["status"] in {"warning", "fail"} for item in rules)
    result = [
        _stage("RECEIVED", "success", "Document received; SHA-256 recorded.", 24),
        _stage("FILE_VALIDATION", "success", f"{record['mime_type']}; server limits passed.", 18),
        _stage(
            "TEXT_EXTRACTION",
            "failed" if status == "failed" else "success",
            "OCR produced no readable text."
            if status == "failed"
            else f"{len(pages)} page(s), {len(record.get('source_text', '')):,} characters.",
            sum(page["latency_ms"] for page in pages),
        ),
    ]
    if status == "failed":
        result.extend(
            _stage(name, "skipped", "Skipped because text extraction failed.", 0)
            for name in (
                "DOCUMENT_CLASSIFICATION",
                "STRUCTURED_EXTRACTION",
                "DETERMINISTIC_VALIDATION",
                "CONFIDENCE_SCORING",
            )
        )
        result.append(_stage("FAILED", "failed", "Text extraction failed; retry is available.", 0))
        return result
    result.extend(
        [
            _stage(
                "DOCUMENT_CLASSIFICATION",
                "warning" if record["document_type"] == "unknown" else "success",
                record.get("classification_reason", "Supported structural signals matched."),
                109,
            ),
            _stage(
                "STRUCTURED_EXTRACTION",
                "skipped" if not record.get("ground_truth") else "success",
                "No schema forced for an unknown document."
                if not record.get("ground_truth")
                else "Strict schema validated.",
                384,
            ),
            _stage(
                "DETERMINISTIC_VALIDATION",
                "skipped" if not rules else ("warning" if warning else "success"),
                "No supported schema selected."
                if not rules
                else f"{sum(item['status'] == 'pass' for item in rules)} rules passed.",
                42,
            ),
            _stage(
                "CONFIDENCE_SCORING",
                "warning" if status == "needs_review" else "success",
                f"Overall confidence {score:.0%}.",
                19,
            ),
            _stage(
                status.upper(),
                "warning" if status == "needs_review" else "success",
                reason or "Acceptance gates passed.",
                0,
            ),
        ]
    )
    return result


def _stage(name: str, status: str, summary: str, duration_ms: float) -> dict:
    return {
        "name": name,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "summary": summary,
        "error": summary if status == "failed" else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    seed_demo(reset=args.reset)
