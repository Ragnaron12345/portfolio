from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import comparison_payload, failure_payload
from app.database import Base
from app.models import Dataset, ExperimentDefinition, ExperimentRun, ModelConfig, PromptVersion, RetrievalConfig
from app.reports import generate_report
from app.runner import create_run, execute_run, matrix_size


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.runner.SessionLocal", factory)
    return factory


def create_entities(session, case_count: int = 2):
    cases = []
    ids = [1, 7] if case_count == 2 else list(range(1, case_count + 1))
    for number in ids:
        cases.append(
            {
                "id": f"case_{number:03d}",
                "input": "What is the answer?",
                "reference_answer": "The answer is documented.",
                "expected_keywords": ["answer", "documented"],
                "forbidden_claims": ["guaranteed approval"],
                "context": ["doc_answer::The answer is documented."],
                "expected_citations": ["doc_answer"],
                "metadata": {"category": "grounded_qa", "difficulty": "easy"},
            }
        )
    dataset = Dataset(name="Test", version="1", content_hash=f"hash-{case_count}", case_count=case_count, cases=cases)
    model_a = ModelConfig(
        name="Model A",
        provider="mock",
        model="mock-standard-v1",
        retries=2,
        input_price_per_million=1,
        output_price_per_million=2,
    )
    model_b = ModelConfig(
        name="Model B",
        provider="mock",
        model="mock-candidate-v2",
        retries=2,
        input_price_per_million=1,
        output_price_per_million=2,
    )
    prompt_a = PromptVersion(
        name="Prompt", semantic_version="1.0.0", system_prompt="Answer", user_template="{context}\n{input}", tags=[]
    )
    prompt_b = PromptVersion(
        name="Prompt",
        semantic_version="2.0.0",
        system_prompt="Answer exactly",
        user_template="{context}\n{input}",
        tags=[],
    )
    retrieval = RetrievalConfig(
        name="top3", chunk_size=400, overlap=50, top_k=3, reranker_enabled=False, embedding_model="mock", mode="vector"
    )
    session.add_all([dataset, model_a, model_b, prompt_a, prompt_b, retrieval])
    session.flush()
    return dataset, model_a, model_b, prompt_a, prompt_b, retrieval


def test_matrix_expansion_2_by_2_by_10(session_factory) -> None:
    with session_factory() as session:
        dataset, model_a, model_b, prompt_a, prompt_b, retrieval = create_entities(session, 10)
        experiment = ExperimentDefinition(
            name="40 generations",
            dataset_id=dataset.id,
            model_config_ids=[model_a.id, model_b.id],
            prompt_version_ids=[prompt_a.id, prompt_b.id],
            retrieval_config_ids=[retrieval.id],
            evaluator_config={},
        )
        session.add(experiment)
        session.commit()
        assert matrix_size(experiment, dataset) == 40


@pytest.mark.asyncio
async def test_retries_and_partial_failure_status_are_persisted(session_factory) -> None:
    with session_factory() as session:
        dataset, model_a, _, _, prompt_b, retrieval = create_entities(session)
        experiment = ExperimentDefinition(
            name="Partial failure",
            dataset_id=dataset.id,
            model_config_ids=[model_a.id],
            prompt_version_ids=[prompt_b.id],
            retrieval_config_ids=[retrieval.id],
            evaluator_config={"concurrency": 2},
        )
        session.add(experiment)
        session.commit()
        run = create_run(session, experiment, force_partial_failures=True)
        run_id = run.id
    await execute_run(run_id, delay_seconds=0)
    with session_factory() as session:
        run = session.get(ExperimentRun, run_id)
        assert run.status == "completed_with_errors"
        assert (run.completed, run.successful, run.failed) == (2, 1, 1)
        assert run.retried == 2


@pytest.mark.asyncio
async def test_report_is_generated_from_persisted_results(session_factory, tmp_path: Path) -> None:
    with session_factory() as session:
        dataset, model_a, model_b, prompt_a, prompt_b, retrieval = create_entities(session)
        experiment = ExperimentDefinition(
            name="Measured comparison",
            dataset_id=dataset.id,
            model_config_ids=[model_a.id, model_b.id],
            prompt_version_ids=[prompt_a.id, prompt_b.id],
            retrieval_config_ids=[retrieval.id],
            evaluator_config={"enable_judge": True, "concurrency": 4},
        )
        session.add(experiment)
        session.commit()
        run = create_run(session, experiment)
        run_id = run.id
    await execute_run(run_id, delay_seconds=0)
    with session_factory() as session:
        run = session.scalar(select(ExperimentRun).where(ExperimentRun.id == run_id))
        comparison = comparison_payload(run)
        regressions = failure_payload(run, regressions_only=True)
        report = generate_report(session, run)
        assert comparison["metrics"]
        assert "Metric comparison" in report.markdown
        assert run.id in report.markdown
        assert report.json_payload["regressions"]["total"] == regressions["total"]
        assert "$1.82" not in report.markdown
