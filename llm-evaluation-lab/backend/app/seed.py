import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Dataset, ExperimentDefinition, ExperimentRun, ModelConfig, PromptVersion, RetrievalConfig
from .runner import create_run

REQUIRED_CASE_FIELDS = {
    "id",
    "input",
    "reference_answer",
    "expected_keywords",
    "forbidden_claims",
    "context",
    "expected_citations",
    "metadata",
}


def load_jsonl(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    cases = []
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        missing = REQUIRED_CASE_FIELDS - set(item)
        if missing:
            raise ValueError(f"Dataset line {line_number} is missing: {', '.join(sorted(missing))}")
        cases.append(item)
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset case IDs must be unique")
    return cases, hashlib.sha256(raw).hexdigest()


def _first(session: Session, model, name: str):
    return session.scalar(select(model).where(model.name == name))


def seed_database(session: Session) -> list[str]:
    settings = get_settings()
    dataset_path = settings.resolved_dataset_path()
    cases, digest = load_jsonl(dataset_path)
    dataset = session.scalar(select(Dataset).where(Dataset.content_hash == digest))
    if dataset is None:
        dataset = Dataset(
            name="EvalForge synthetic benchmark",
            version="2.0.0",
            content_hash=digest,
            case_count=len(cases),
            cases=cases,
        )
        session.add(dataset)
        session.flush()

    models = []
    model_specs = [
        {
            "name": "Mock Standard",
            "provider": "mock",
            "model": "mock-standard-v1",
            "temperature": 0.0,
            "max_tokens": 512,
            "timeout_seconds": 10,
            "retries": 1,
            "input_price_per_million": 0.20,
            "output_price_per_million": 0.80,
            "pricing_source": "EvalForge synthetic demonstration pricing",
        },
        {
            "name": "Mock Candidate",
            "provider": "mock",
            "model": "mock-candidate-v2",
            "temperature": 0.0,
            "max_tokens": 512,
            "timeout_seconds": 10,
            "retries": 1,
            "input_price_per_million": 0.30,
            "output_price_per_million": 1.00,
            "pricing_source": "EvalForge synthetic demonstration pricing",
        },
        {
            "name": "Mock Flaky",
            "provider": "mock",
            "model": "mock-flaky-v1",
            "temperature": 0.0,
            "max_tokens": 512,
            "timeout_seconds": 2,
            "retries": 2,
            "input_price_per_million": 0.10,
            "output_price_per_million": 0.40,
            "pricing_source": "EvalForge synthetic demonstration pricing",
        },
    ]
    for spec in model_specs:
        item = _first(session, ModelConfig, spec["name"])
        if item is None:
            item = ModelConfig(**spec)
            session.add(item)
            session.flush()
        models.append(item)

    prompts = []
    prompt_specs = [
        {
            "name": "Grounded answer",
            "semantic_version": "1.0.0",
            "system_prompt": "Answer concisely from the supplied context. Do not invent facts.",
            "user_template": "Context:\n{context}\n\nQuestion: {input}\nAnswer:",
            "tags": ["baseline-compatible", "grounded"],
        },
        {
            "name": "Grounded answer",
            "semantic_version": "2.1.0",
            "system_prompt": (
                "Use only supplied evidence, preserve requested structure, cite source IDs, "
                "and state when information is missing."
            ),
            "user_template": (
                "Evidence:\n{context}\n\nTask: {input}\nReturn a precise answer with source IDs when evidence exists."
            ),
            "tags": ["candidate", "citations", "structured"],
        },
    ]
    for spec in prompt_specs:
        item = session.scalar(
            select(PromptVersion).where(
                PromptVersion.name == spec["name"], PromptVersion.semantic_version == spec["semantic_version"]
            )
        )
        if item is None:
            item = PromptVersion(**spec)
            session.add(item)
            session.flush()
        prompts.append(item)

    retrievals = []
    retrieval_specs = [
        {
            "name": "Vector top-3 · chunk 400",
            "chunk_size": 400,
            "overlap": 60,
            "top_k": 3,
            "reranker_enabled": False,
            "embedding_model": "mock-embedding-v1",
            "mode": "vector",
        },
        {
            "name": "Vector top-5 · chunk 800",
            "chunk_size": 800,
            "overlap": 120,
            "top_k": 5,
            "reranker_enabled": False,
            "embedding_model": "mock-embedding-v1",
            "mode": "vector",
        },
        {
            "name": "Reranked top-5",
            "chunk_size": 800,
            "overlap": 120,
            "top_k": 5,
            "reranker_enabled": True,
            "embedding_model": "mock-embedding-v1",
            "mode": "hybrid",
        },
    ]
    for spec in retrieval_specs:
        item = _first(session, RetrievalConfig, spec["name"])
        if item is None:
            item = RetrievalConfig(**spec)
            session.add(item)
            session.flush()
        retrievals.append(item)

    session.commit()
    if session.scalar(select(ExperimentRun).limit(1)) is not None:
        return []

    main_experiment = ExperimentDefinition(
        name="Model × prompt quality benchmark",
        dataset_id=dataset.id,
        model_config_ids=[models[0].id, models[1].id],
        prompt_version_ids=[prompts[0].id, prompts[1].id],
        retrieval_config_ids=[retrievals[0].id],
        evaluator_config={"enable_judge": True, "concurrency": 8, "judge_model": "mock-judge-v1"},
        max_estimated_cost=2.0,
    )
    partial_experiment = ExperimentDefinition(
        name="Partial provider failure drill",
        dataset_id=dataset.id,
        model_config_ids=[models[2].id],
        prompt_version_ids=[prompts[1].id],
        retrieval_config_ids=[retrievals[1].id],
        evaluator_config={"enable_judge": False, "concurrency": 6},
        max_estimated_cost=0.5,
    )
    rag_experiment = ExperimentDefinition(
        name="RAG retrieval configuration sweep",
        dataset_id=dataset.id,
        model_config_ids=[models[1].id],
        prompt_version_ids=[prompts[1].id],
        retrieval_config_ids=[item.id for item in retrievals],
        evaluator_config={"enable_judge": True, "concurrency": 8, "judge_model": "mock-judge-v1"},
        max_estimated_cost=2.0,
    )
    session.add_all([main_experiment, partial_experiment, rag_experiment])
    session.commit()
    main_run = create_run(session, main_experiment)
    partial_run = create_run(session, partial_experiment, force_partial_failures=True)
    rag_run = create_run(session, rag_experiment)
    return [main_run.id, partial_run.id, rag_run.id]


def recover_stale_runs(session: Session) -> int:
    stale = list(session.scalars(select(ExperimentRun).where(ExperimentRun.status.in_(["queued", "running"]))))
    for run in stale:
        run.status = "completed_with_errors" if run.completed else "failed"
        run.recovery_note = "Recovered after process restart; unfinished work was not replayed automatically."
    session.commit()
    return len(stale)
