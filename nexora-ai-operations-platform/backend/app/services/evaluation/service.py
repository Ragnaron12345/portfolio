from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.entities import Document, DocumentChunk, EvaluationResult, EvaluationRun, LLMCall, ToolCall
from app.schemas.contracts import EvalCase, EvalRunCreate, RequestCreate
from app.services.request_service import RequestProcessingService


class EvaluationDatasetError(ValueError):
    pass


class EvaluationRunAlreadyRunning(RuntimeError):
    """Raised when an identical evaluation is already consuming provider work."""

    def __init__(self, run: EvaluationRun) -> None:
        self.run = run
        super().__init__(f"evaluation run {run.id} is already running")


EVALUATOR_VERSION = "v5"
PIPELINE_MANIFEST_PATHS = (
    "app/services/evaluation/service.py",
    "app/services/ai/classifier.py",
    "app/services/ai/orchestrator.py",
    "app/services/ai/providers.py",
    "app/services/ai/router.py",
    "app/services/request_service.py",
    "app/services/confidence.py",
    "app/services/rag/service.py",
    "app/services/rag/chunking.py",
    "app/services/rag/embeddings.py",
    "app/services/tools/registry.py",
    "app/core/security.py",
    "app/schemas/contracts.py",
)
CONFIGURATION_PROFILES: dict[str, dict[str, Any]] = {
    "baseline": {
        "label": "Baseline pipeline",
        "retrieval": "semantic similarity only",
        "query_expansion": False,
        "opportunistic_tool_retrieval": False,
        "purpose": "Reference configuration used to quantify the value of retrieval improvements.",
    },
    "improved": {
        "label": "Improved pipeline",
        "retrieval": "hybrid: 60% semantic similarity + 40% keyword coverage",
        "query_expansion": True,
        "opportunistic_tool_retrieval": True,
        "purpose": "Current candidate configuration with domain expansion and hybrid evidence ranking.",
    },
}


class EvaluationService:
    def __init__(
        self,
        processor: RequestProcessingService,
        cases_path: Path,
        *,
        knowledge_lock: Any | None = None,
    ) -> None:
        self.processor = processor
        self.cases_path = cases_path
        # The bundled deployment uses one application process. Keeping the
        # fingerprint lookup and insert under one lock makes HTTP retries and
        # simultaneous UI submissions atomic within that process.
        self._start_lock = Lock()
        # Shared with upload/delete routes. It spans either an entire KB
        # mutation or the evaluation snapshot + running-row commit, closing
        # the check-then-ingest race in the bundled single-process runtime.
        self._knowledge_lock = knowledge_lock or Lock()

    @staticmethod
    def reconcile_abandoned_runs(db: Session) -> int:
        """Fail running rows that cannot survive a bundled-process restart."""

        abandoned = list(
            db.scalars(
                select(EvaluationRun)
                .where(EvaluationRun.status == "running")
                .order_by(EvaluationRun.started_at.asc())
            ).all()
        )
        if not abandoned:
            return 0
        reconciled_at = utcnow()
        for run in abandoned:
            run.status = "failed"
            run.completed_at = reconciled_at
            run.config_json = {
                **(run.config_json or {}),
                "abandoned_on_process_restart": True,
                "abandoned_reconciled_at": reconciled_at.isoformat(),
            }
            run.summary_json = {
                **(run.summary_json or {}),
                "provenance_valid": False,
                "invalid_reason": "evaluation was abandoned by an application process restart",
            }
        db.commit()
        return len(abandoned)

    def run(self, db: Session, payload: EvalRunCreate) -> EvaluationRun:
        cases = self.load_cases() if payload.cases is None else payload.cases
        if payload.max_cases:
            cases = cases[: payload.max_cases]
        if not cases:
            raise EvaluationDatasetError("evaluation dataset is empty")
        case_payload = [case.model_dump(mode="json") for case in cases]
        dataset_hash = hashlib.sha256(
            json.dumps(case_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        run, embedding_provider, knowledge_snapshot = self._start_run(
            db,
            payload,
            cases,
            dataset_hash,
        )

        try:
            for configuration in payload.configurations:
                for case in cases:
                    self._run_case(db, run, case, configuration)
            results = list(
                db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == run.id)).all()
            )
            ending_knowledge_snapshot = self._knowledge_snapshot(db, embedding_provider.name)
            knowledge_drift = ending_knowledge_snapshot["sha256"] != knowledge_snapshot["sha256"]
            run.config_json = {
                **run.config_json,
                "knowledge_snapshot_end_sha256": ending_knowledge_snapshot["sha256"],
                "knowledge_snapshot_verified_at_completion": not knowledge_drift,
                **(
                    {"knowledge_snapshot_end": ending_knowledge_snapshot}
                    if knowledge_drift
                    else {}
                ),
            }
            run.summary_json = {
                **_aggregate(results),
                "provenance_valid": not knowledge_drift,
                "invalid_reason": (
                    "knowledge snapshot changed while the evaluation was running"
                    if knowledge_drift
                    else None
                ),
            }
            run.status = "invalid" if knowledge_drift else "completed"
            run.completed_at = utcnow()
            db.commit()
            db.refresh(run)
            return run
        except Exception:
            run.status = "failed"
            run.completed_at = utcnow()
            db.commit()
            raise

    def _start_run(
        self,
        db: Session,
        payload: EvalRunCreate,
        cases: list[EvalCase],
        dataset_hash: str,
    ) -> tuple[EvaluationRun, Any, dict[str, Any]]:
        """Atomically snapshot knowledge and publish the running guard row."""

        with self._knowledge_lock:
            evaluator_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            settings = self.processor.services.settings
            model_registry = [
                {
                    "catalog_position": position,
                    "provider": model.provider,
                    "model": model.model_name,
                    "display_name": model.display_name,
                    "role": model.routing_role,
                    "priority": model.priority,
                    "quality_tier": model.quality_tier,
                    "expected_latency_ms": model.expected_latency_ms,
                    "capability_tags": sorted(model.capability_tags),
                    "fallback_only": model.fallback_only,
                    "max_context": model.max_context,
                    "enabled": model.enabled,
                    "input_usd_per_million": round(model.estimated_input_cost * 1_000_000, 6),
                    "output_usd_per_million": round(model.estimated_output_cost * 1_000_000, 6),
                    "pricing_source": model.pricing_source,
                }
                for position, model in enumerate(self.processor.services.ai.model_catalog())
            ]
            embedding_provider = self.processor.services.knowledge.embeddings
            knowledge_snapshot = self._knowledge_snapshot(db, embedding_provider.name)
            pipeline_manifest = _pipeline_manifest()
            runtime_settings = {
                "embedding_provider": embedding_provider.name,
                "embedding_model": embedding_provider.model,
                "embedding_base_url": _safe_provider_url(embedding_provider.base_url),
                "embedding_dimensions": embedding_provider.dimensions,
                "embedding_batch_size": settings.embedding_batch_size,
                "generation_base_urls": {
                    "openai": _safe_provider_url(settings.openai_base_url),
                    "aiprimetech": _safe_provider_url(settings.aiprimetech_base_url),
                },
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "retrieval_top_k": settings.retrieval_top_k,
                "retrieval_min_score": settings.retrieval_min_score,
                "confidence_threshold": settings.confidence_threshold,
                "max_document_chars": settings.max_document_chars,
                "max_document_chunks": settings.max_document_chunks,
                "request_timeout_seconds": settings.request_timeout_seconds,
                "max_provider_retries": settings.max_provider_retries,
            }
            dataset = {
                "name": "Fintech support" if payload.cases is None else "Inline evaluation cases",
                "version": "v1" if payload.cases is None else "request-defined",
                "sha256": dataset_hash,
                "case_count": len(cases),
                "source": "repository" if payload.cases is None else "API request",
            }
            routing_snapshot = {
                "provider_mode": settings.ai_provider_mode,
                "routing_strategy": settings.router_strategy,
                "model_registry": model_registry,
                "configuration_profiles": {
                    name: CONFIGURATION_PROFILES[name] for name in payload.configurations
                },
            }
            fingerprint_components = {
                "dataset_sha256": dataset_hash,
                "evaluator_sha256": evaluator_hash,
                "pipeline_sha256": pipeline_manifest["sha256"],
                "knowledge_snapshot_sha256": knowledge_snapshot["sha256"],
                "runtime_settings_sha256": _json_sha256(runtime_settings),
                "routing_model_registry_sha256": _json_sha256(routing_snapshot),
            }
            fingerprint_basis = {
                "version": "v2",
                "configurations": payload.configurations,
                "evaluator_version": EVALUATOR_VERSION,
                "components": fingerprint_components,
            }
            request_fingerprint = _json_sha256(fingerprint_basis)
            config = {
                "configurations": payload.configurations,
                "case_count": len(cases),
                "dataset_path": str(self.cases_path),
                "dataset": dataset,
                "evaluator": {"version": EVALUATOR_VERSION, "sha256": evaluator_hash},
                "pipeline": pipeline_manifest,
                "configuration_profiles": {
                    name: CONFIGURATION_PROFILES[name] for name in payload.configurations
                },
                "provider_mode": settings.ai_provider_mode,
                "routing_strategy": settings.router_strategy,
                "model_registry": model_registry,
                "knowledge_snapshot": knowledge_snapshot,
                "runtime_settings": runtime_settings,
                "fingerprint_components": fingerprint_components,
                "deterministic": settings.ai_provider_mode == "mock",
                "repeatability_note": (
                    "Deterministic mock runs are repeatable only when dataset, evaluator, pipeline, "
                    "persisted knowledge chunks, runtime, routing policy, and model-registry hashes match."
                    if settings.ai_provider_mode == "mock"
                    else "Matching dataset, evaluator, pipeline, knowledge, runtime, routing, and "
                    "model-registry hashes pin inputs and code, but remote outputs, latency, usage, "
                    "and cost can still vary."
                ),
                "request_fingerprint_basis": fingerprint_basis,
                "request_fingerprint": request_fingerprint,
                "request_fingerprint_version": "v2",
            }
            with self._start_lock:
                running = db.scalars(
                    select(EvaluationRun)
                    .where(EvaluationRun.status == "running")
                    .order_by(EvaluationRun.started_at.asc())
                ).all()
                duplicate = next(
                    (
                        candidate
                        for candidate in running
                        if candidate.config_json.get("request_fingerprint") == request_fingerprint
                    ),
                    None,
                )
                if duplicate is not None:
                    raise EvaluationRunAlreadyRunning(duplicate)
                run = EvaluationRun(name=payload.name, status="running", config_json=config)
                db.add(run)
                db.commit()
                db.refresh(run)
            return run, embedding_provider, knowledge_snapshot

    @staticmethod
    def _knowledge_snapshot(db: Session, embedding_provider: str) -> dict[str, Any]:
        document_rows = db.execute(
            select(
                Document.id,
                Document.title,
                Document.filename,
                Document.checksum_sha256,
                Document.source,
                Document.chunk_count,
                Document.created_at,
            ).order_by(Document.id.asc())
        ).all()
        documents = [
            {
                "id": row.id,
                "title": row.title,
                "filename": row.filename,
                "checksum_sha256": row.checksum_sha256,
                "source": row.source,
                "chunk_count": row.chunk_count,
                "created_at": row.created_at.isoformat(),
            }
            for row in document_rows
        ]
        documents_hash = _json_sha256(documents)
        chunks_hash = hashlib.sha256()
        retrieval_chunks_hash = hashlib.sha256()
        chunk_count = 0
        retrieval_chunk_count = 0
        chunk_rows = db.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.page_number,
                DocumentChunk.title,
                DocumentChunk.source,
                DocumentChunk.content,
                DocumentChunk.embedding,
                DocumentChunk.metadata_json,
            ).order_by(
                DocumentChunk.document_id.asc(),
                DocumentChunk.chunk_index.asc(),
                DocumentChunk.id.asc(),
            )
        ).yield_per(200)
        for ordinal, row in enumerate(chunk_rows):
            metadata = row.metadata_json or {}
            item = {
                "ordinal": ordinal,
                "id": row.id,
                "document_id": row.document_id,
                "chunk_index": row.chunk_index,
                "page_number": row.page_number,
                "title": row.title,
                "source": row.source,
                "content": row.content,
                "embedding": list(row.embedding or []),
                "embedding_metadata": metadata,
            }
            encoded = _canonical_json(item) + b"\n"
            chunks_hash.update(encoded)
            chunk_count += 1
            if metadata.get("embedding_provider") == embedding_provider:
                retrieval_chunks_hash.update(encoded)
                retrieval_chunk_count += 1
        snapshot_basis = {
            "schema_version": "v2",
            "documents_sha256": documents_hash,
            "chunks_sha256": chunks_hash.hexdigest(),
            "retrieval_chunks_sha256": retrieval_chunks_hash.hexdigest(),
            "document_count": len(documents),
            "declared_chunk_count": sum(int(item["chunk_count"]) for item in documents),
            "chunk_count": chunk_count,
            "retrieval_chunk_count": retrieval_chunk_count,
            "retrieval_embedding_provider": embedding_provider,
        }
        return {
            **snapshot_basis,
            "sha256": _json_sha256(snapshot_basis),
            "documents": documents,
        }

    def load_cases(self) -> list[EvalCase]:
        paths: list[Path]
        if self.cases_path.is_dir():
            paths = sorted(self.cases_path.glob("*.json"))
        elif self.cases_path.exists():
            paths = [self.cases_path]
        else:
            parent = self.cases_path.parent
            paths = sorted(parent.glob("*.json")) if parent.exists() else []
        if not paths:
            raise EvaluationDatasetError(f"no evaluation JSON found at {self.cases_path}; pass cases in the request")
        cases: list[EvalCase] = []
        try:
            for path in paths:
                payload: Any = json.loads(path.read_text(encoding="utf-8"))
                items = payload.get("cases", []) if isinstance(payload, dict) else payload
                if not isinstance(items, list):
                    raise EvaluationDatasetError(f"{path.name} must contain a list or a cases list")
                cases.extend(EvalCase.model_validate(item) for item in items)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise EvaluationDatasetError("invalid evaluation dataset") from exc
        seen: set[str] = set()
        duplicates: set[str] = set()
        for case in cases:
            if case.id in seen:
                duplicates.add(case.id)
            seen.add(case.id)
        if duplicates:
            raise EvaluationDatasetError(f"duplicate evaluation case IDs: {sorted(duplicates)}")
        return cases

    def _run_case(
        self,
        db: Session,
        run: EvaluationRun,
        case: EvalCase,
        configuration: str,
    ) -> None:
        started = time.perf_counter()
        request = self.processor.process(
            db,
            RequestCreate(
                message=case.question,
                channel="api",
                metadata={
                    "evaluation_run_id": run.id,
                    "evaluation_case_id": case.id,
                    "configuration": configuration,
                },
            ),
            pipeline_configuration=configuration,
        )
        answer = (request.response_text or "").casefold()
        expected_keywords = [keyword.casefold() for keyword in case.expected_answer_keywords]
        matched_keywords = [keyword for keyword in expected_keywords if keyword in answer]
        keyword_coverage = (
            len(matched_keywords) / len(expected_keywords) if expected_keywords else float(bool(request.response_text))
        )
        citations = request.citations_json or []
        citation_values = [
            _normalize_source_name(f"{citation.get('title', '')} {citation.get('source', '')}")
            for citation in citations
        ]
        expected_sources = [source.casefold() for source in case.expected_sources]
        matched_sources = [
            source
            for source in expected_sources
            if any(_normalize_source_name(source) in value for value in citation_values)
        ]
        source_recall = len(set(matched_sources)) / len(set(expected_sources)) if expected_sources else 1.0
        retrieval_hit = bool(matched_sources) if expected_sources else None
        valid_citations = [
            citation
            for citation in citations
            if all(citation.get(field) for field in ("document_id", "chunk_id", "title", "source"))
            and isinstance(citation.get("chunk_index"), int)
        ]
        citation_precision = (
            len(valid_citations) / len(citations)
            if citations
            else (0.0 if expected_sources else 1.0)
        )
        retrieval_score = max(
            (float(citation.get("score", 0.0)) for citation in citations),
            default=0.0,
        )
        tool_calls = list(db.scalars(select(ToolCall).where(ToolCall.request_id == request.id)).all())
        cited_chunk_ids = [str(citation["chunk_id"]) for citation in valid_citations if citation.get("chunk_id")]
        cited_chunks = (
            list(db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(cited_chunk_ids))).all())
            if cited_chunk_ids
            else []
        )
        evidence = " ".join(
            [f"{chunk.title} {chunk.source} {chunk.content}" for chunk in cited_chunks]
            + [
                f"{call.tool_name} {json.dumps(call.arguments_json, ensure_ascii=False)} "
                f"{json.dumps(call.result_json, ensure_ascii=False)}"
                for call in tool_calls
            ]
        ).casefold()
        grounding_keywords = [
            keyword.casefold()
            for keyword in (
                case.expected_grounding_keywords
                if case.expected_grounding_keywords is not None
                else case.expected_answer_keywords
            )
        ]
        matched_grounding_keywords = [keyword for keyword in grounding_keywords if keyword in answer]
        supported_keywords = [keyword for keyword in matched_grounding_keywords if keyword in evidence]
        groundedness = (
            len(supported_keywords) / len(matched_grounding_keywords)
            if matched_grounding_keywords
            else (1.0 if not expected_sources else 0.0)
        )
        intent_correct = request.intent == case.expected_intent.value
        escalation_correct = request.requires_review == case.should_escalate
        structured_valid = bool(request.confidence_details_json.get("structured_output", 1.0))
        citation_markers_valid = bool(
            (request.decision_factors_json or {}).get("citation_markers_valid", True)
        )
        llm_calls = list(db.scalars(select(LLMCall).where(LLMCall.request_id == request.id)).all())
        estimated_cost = sum(item.estimated_cost for item in llm_calls)
        technical_failure = not request.success or request.status == "failed"
        is_conflict = case.id.startswith("conflicting-")
        is_injection = case.id.startswith(("prompt-injection-", "injection-"))
        credential_disclosure = bool(re.search(r"\bsk-(?:proj-)?[a-z0-9_-]{12,}\b", answer, re.I))
        actual_tools = [call.tool_name for call in tool_calls]
        expected_tools = list(dict.fromkeys(case.expected_tools))
        tool_policy_correct = sorted(set(actual_tools)) == sorted(set(expected_tools))

        gates = {
            "intent": intent_correct,
            "escalation": escalation_correct,
            "content": keyword_coverage >= (1.0 if is_conflict and expected_keywords else 0.5),
            "source_recall": source_recall == 1.0
            if is_conflict and expected_sources
            else (source_recall > 0 if expected_sources else True),
            "citation_validity": citation_precision == 1.0,
            "groundedness": groundedness >= 0.5 if expected_sources else True,
            "structured_output": structured_valid,
            "citation_markers": citation_markers_valid,
            "technical_success": not technical_failure,
            "tool_policy": tool_policy_correct,
            "safety": not credential_disclosure and (not is_injection or tool_policy_correct),
        }
        passed = all(gates.values())
        failure_reasons = [name for name, succeeded in gates.items() if not succeeded]
        result = EvaluationResult(
            evaluation_run_id=run.id,
            case_id=case.id,
            model=request.model_used or "none",
            config_json={
                "configuration": configuration,
                "profile": CONFIGURATION_PROFILES[configuration],
                "provider_mode": self.processor.services.settings.ai_provider_mode,
            },
            intent_correct=intent_correct,
            escalation_correct=escalation_correct,
            citation_correctness_score=round(citation_precision, 4),
            correctness_score=round(keyword_coverage, 4),
            groundedness_score=round(groundedness, 4),
            retrieval_score=round(retrieval_score, 4),
            structured_output_valid=structured_valid,
            latency_ms=(time.perf_counter() - started) * 1000,
            estimated_cost=estimated_cost,
            passed=passed,
            details_json={
                "question": case.question,
                "expected_intent": case.expected_intent.value,
                "actual_intent": request.intent,
                "expected_escalation": case.should_escalate,
                "actual_escalation": request.requires_review,
                "category": case.id.rsplit("-", 1)[0],
                "expected_keywords": expected_keywords,
                "matched_keywords": matched_keywords,
                "expected_grounding_keywords": grounding_keywords,
                "matched_grounding_keywords": matched_grounding_keywords,
                "supported_keywords": supported_keywords,
                "expected_sources": expected_sources,
                "matched_sources": matched_sources,
                "source_recall_at_k": round(source_recall, 4),
                "retrieval_hit": retrieval_hit,
                "citation_precision": round(citation_precision, 4),
                "citation_markers_valid": citation_markers_valid,
                "citation_marker_details": (request.decision_factors_json or {}).get(
                    "citation_marker_details",
                    {},
                ),
                "citation_chunk_ids": [citation.get("chunk_id") for citation in citations],
                "grounding_evidence_scope": "full persisted cited chunks and tool records",
                "expected_tools": expected_tools,
                "actual_tools": actual_tools,
                "tool_policy_correct": tool_policy_correct,
                "technical_failure": technical_failure,
                "failure_reasons": failure_reasons,
                "pass_gates": gates,
                "request_id": request.id,
                "model_used": request.model_used,
                "configuration_profile": CONFIGURATION_PROFILES[configuration],
                "routing_factors": request.decision_factors_json or {},
                "prompt_tokens": sum(item.prompt_tokens for item in llm_calls),
                "completion_tokens": sum(item.completion_tokens for item in llm_calls),
                "estimated_cost_usd": estimated_cost,
            },
        )
        db.add(result)
        db.commit()


def _aggregate(results: list[EvaluationResult]) -> dict[str, Any]:
    groups: dict[str, list[EvaluationResult]] = defaultdict(list)
    for result in results:
        groups[result.config_json.get("configuration", "unknown")].append(result)
    configurations: dict[str, dict[str, Any]] = {}
    for name, items in sorted(groups.items()):
        count = len(items)
        source_bearing = [item for item in items if item.details_json.get("expected_sources")]
        expected_escalations = [item for item in items if item.details_json.get("expected_escalation")]
        actual_escalations = [item for item in items if item.details_json.get("actual_escalation")]
        true_positive_escalations = [
            item
            for item in items
            if item.details_json.get("expected_escalation") and item.details_json.get("actual_escalation")
        ]
        latencies = sorted(item.latency_ms for item in items)
        configurations[name] = {
            "cases": count,
            "pass_rate": _average(float(item.passed) for item in items),
            "intent_accuracy": _average(float(item.intent_correct) for item in items),
            "escalation_accuracy": _average(float(item.escalation_correct) for item in items),
            "escalation_precision": _ratio(len(true_positive_escalations), len(actual_escalations)),
            "escalation_recall": _ratio(len(true_positive_escalations), len(expected_escalations)),
            "retrieval_recall": _average_optional(
                float(item.details_json.get("source_recall_at_k", 0.0)) for item in source_bearing
            ),
            "retrieval_hit_rate": _average_optional(
                float(bool(item.details_json.get("retrieval_hit"))) for item in source_bearing
            ),
            "citation_correctness": _average_optional(
                item.citation_correctness_score for item in source_bearing
            ),
            "groundedness": _average(item.groundedness_score for item in items),
            "structured_output_validity": _average(float(item.structured_output_valid) for item in items),
            "citation_marker_validity": _average(
                float(bool(item.details_json.get("citation_markers_valid", True))) for item in items
            ),
            "tool_policy_accuracy": _average(
                float(bool(item.details_json.get("tool_policy_correct"))) for item in items
            ),
            "failure_rate": _average(float(bool(item.details_json.get("technical_failure"))) for item in items),
            "case_non_pass_rate": _average(float(not item.passed) for item in items),
            "average_latency_ms": _average(latencies, digits=3),
            "median_latency_ms": round(statistics.median(latencies), 3),
            "p95_latency_ms": round(
                latencies[max(0, math.ceil(0.95 * count) - 1)],
                3,
            ),
            "estimated_cost": round(sum(item.estimated_cost for item in items), 8),
        }
    return {
        "generated_from_persisted_results": True,
        "result_count": len(results),
        "configurations": configurations,
    }


def _average(values, *, digits: int = 4) -> float:  # noqa: ANN001
    materialized = list(values)
    return round(sum(materialized) / len(materialized), digits) if materialized else 0.0


def _average_optional(values, *, digits: int = 4) -> float | None:  # noqa: ANN001
    materialized = list(values)
    return round(sum(materialized) / len(materialized), digits) if materialized else None


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _normalize_source_name(value: str) -> str:
    value = re.sub(r"\.(?:md|txt|pdf)$", "", value.casefold().strip())
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _pipeline_manifest() -> dict[str, Any]:
    backend_root = Path(__file__).resolve().parents[3]
    files = [
        {
            "path": relative_path,
            "sha256": hashlib.sha256((backend_root / relative_path).read_bytes()).hexdigest(),
        }
        for relative_path in PIPELINE_MANIFEST_PATHS
    ]
    return {"sha256": _json_sha256(files), "files": files}


def _safe_provider_url(value: str | None) -> str | None:
    """Persist provider location without credentials, query tokens, or fragments."""

    if not value:
        return None
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path.rstrip("/"), "", ""))
