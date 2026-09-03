import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .analytics import case_payload, comparison_payload, failure_payload, run_summary
from .config import get_settings
from .database import SessionLocal, get_db, init_database
from .models import (
    CaseResult,
    Dataset,
    ExperimentDefinition,
    ExperimentRun,
    ModelConfig,
    PromptVersion,
    RetrievalConfig,
)
from .reports import generate_report
from .runner import create_run, execute_run, load_run_with_results, matrix_size, schedule_run
from .schemas import (
    DatasetCreate,
    ExperimentCreate,
    ModelConfigCreate,
    PromptVersionCreate,
    RetrievalConfigCreate,
    RunCreate,
)
from .seed import recover_stale_runs, seed_database

settings = get_settings()


def _entity_dict(item) -> dict:
    result = {column.name: getattr(item, column.name) for column in item.__table__.columns}
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    seed_run_ids: list[str] = []
    with SessionLocal() as session:
        recover_stale_runs(session)
        if settings.auto_seed:
            seed_run_ids = seed_database(session)
    for run_id in seed_run_ids:
        await execute_run(run_id, delay_seconds=0)
    yield
    pending = [
        task for task in list(__import__("app.runner", fromlist=["RUN_TASKS"]).RUN_TASKS.values()) if not task.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(
    title="EvalForge API",
    version="2.0.0",
    description="Reproducible evaluation platform for LLMs, prompts and RAG pipelines.",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

Db = Annotated[Session, Depends(get_db)]


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "service": "evalforge", "provider_mode": settings.provider_mode}


@app.post("/api/v1/datasets", status_code=status.HTTP_201_CREATED)
def create_dataset(payload: DatasetCreate, db: Db) -> dict:
    canonical = "\n".join(json.dumps(case, sort_keys=True, separators=(",", ":")) for case in payload.cases)
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    existing = db.scalar(select(Dataset).where(Dataset.content_hash == content_hash))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "A dataset with this exact content already exists")
    item = Dataset(
        name=payload.name,
        version=payload.version,
        content_hash=content_hash,
        case_count=len(payload.cases),
        cases=payload.cases,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _entity_dict(item)


@app.get("/api/v1/datasets")
def list_datasets(db: Db) -> list[dict]:
    return [
        _entity_dict(item) | {"cases": None} for item in db.scalars(select(Dataset).order_by(Dataset.created_at.desc()))
    ]


@app.get("/api/v1/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Db) -> dict:
    item = db.get(Dataset, dataset_id)
    if item is None:
        raise HTTPException(404, "Dataset not found")
    return _entity_dict(item)


@app.post("/api/v1/models", status_code=status.HTTP_201_CREATED)
def create_model(payload: ModelConfigCreate, db: Db) -> dict:
    item = ModelConfig(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _entity_dict(item)


@app.get("/api/v1/models")
def list_models(db: Db) -> list[dict]:
    return [_entity_dict(item) for item in db.scalars(select(ModelConfig).order_by(ModelConfig.created_at))]


@app.post("/api/v1/prompts", status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptVersionCreate, db: Db) -> dict:
    item = PromptVersion(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _entity_dict(item)


@app.get("/api/v1/prompts")
def list_prompts(db: Db) -> list[dict]:
    return [_entity_dict(item) for item in db.scalars(select(PromptVersion).order_by(PromptVersion.created_at))]


@app.get("/api/v1/prompts/{prompt_id}")
def get_prompt(prompt_id: str, db: Db) -> dict:
    item = db.get(PromptVersion, prompt_id)
    if item is None:
        raise HTTPException(404, "Prompt version not found")
    return _entity_dict(item)


@app.post("/api/v1/retrieval-configs", status_code=status.HTTP_201_CREATED)
def create_retrieval(payload: RetrievalConfigCreate, db: Db) -> dict:
    item = RetrievalConfig(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _entity_dict(item)


@app.get("/api/v1/retrieval-configs")
def list_retrievals(db: Db) -> list[dict]:
    return [_entity_dict(item) for item in db.scalars(select(RetrievalConfig).order_by(RetrievalConfig.created_at))]


def _validate_ids(db: Session, model, ids: list[str], label: str) -> None:
    found = set(db.scalars(select(model.id).where(model.id.in_(ids))))
    missing = set(ids) - found
    if missing:
        raise HTTPException(422, f"Unknown {label}: {', '.join(sorted(missing))}")


@app.post("/api/v1/experiments", status_code=status.HTTP_201_CREATED)
def create_experiment(payload: ExperimentCreate, db: Db) -> dict:
    _validate_ids(db, Dataset, [payload.dataset_id], "dataset")
    _validate_ids(db, ModelConfig, payload.model_config_ids, "model configs")
    _validate_ids(db, PromptVersion, payload.prompt_version_ids, "prompt versions")
    _validate_ids(db, RetrievalConfig, payload.retrieval_config_ids, "retrieval configs")
    item = ExperimentDefinition(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _entity_dict(item) | {"matrix_size": matrix_size(item, db.get(Dataset, item.dataset_id))}


@app.get("/api/v1/experiments")
def list_experiments(db: Db) -> list[dict]:
    result = []
    for item in db.scalars(select(ExperimentDefinition).order_by(ExperimentDefinition.created_at.desc())):
        result.append(_entity_dict(item) | {"matrix_size": matrix_size(item, db.get(Dataset, item.dataset_id))})
    return result


@app.get("/api/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str, db: Db) -> dict:
    item = db.get(ExperimentDefinition, experiment_id)
    if item is None:
        raise HTTPException(404, "Experiment not found")
    return _entity_dict(item) | {"matrix_size": matrix_size(item, db.get(Dataset, item.dataset_id))}


@app.post("/api/v1/experiments/{experiment_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(experiment_id: str, payload: RunCreate, db: Db) -> dict:
    experiment = db.get(ExperimentDefinition, experiment_id)
    if experiment is None:
        raise HTTPException(404, "Experiment not found")
    active = db.scalar(
        select(ExperimentRun).where(
            ExperimentRun.experiment_id == experiment_id,
            ExperimentRun.status.in_(["queued", "running"]),
        )
    )
    if active:
        raise HTTPException(409, f"Experiment already has active run {active.id}")
    run = create_run(db, experiment, payload.force_partial_failures)
    schedule_run(run.id)
    return run_summary(run)


def _run_or_404(db: Session, run_id: str) -> ExperimentRun:
    run = load_run_with_results(db, run_id)
    if run is None:
        raise HTTPException(404, "Selected run no longer exists")
    return run


@app.get("/api/v1/runs")
def list_runs(db: Db, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    runs = db.scalars(
        select(ExperimentRun)
        .options(selectinload(ExperimentRun.case_results), selectinload(ExperimentRun.experiment))
        .order_by(ExperimentRun.created_at.desc())
        .limit(limit)
    )
    return [run_summary(run) for run in runs]


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, db: Db) -> dict:
    return run_summary(_run_or_404(db, run_id))


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Db) -> dict:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status not in {"queued", "running"}:
        raise HTTPException(409, f"Run is already {run.status}")
    run.cancel_requested = True
    db.commit()
    return {"id": run.id, "status": run.status, "cancel_requested": True}


@app.get("/api/v1/runs/{run_id}/results")
def get_results(
    run_id: str,
    db: Db,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    run = _run_or_404(db, run_id)
    rows = run.case_results[offset : offset + limit]
    return {
        "run_id": run.id,
        "items": [case_payload(row) for row in rows],
        "total": len(run.case_results),
        "offset": offset,
        "limit": limit,
    }


@app.get("/api/v1/runs/{run_id}/failures")
def get_failures(
    run_id: str,
    db: Db,
    model: str | None = None,
    prompt: str | None = None,
    retrieval: str | None = None,
    category: str | None = None,
    failure_type: str | None = None,
    regressions_only: bool = False,
) -> dict:
    return failure_payload(
        _run_or_404(db, run_id),
        model_config_id=model,
        prompt_version_id=prompt,
        retrieval_config_id=retrieval,
        category=category,
        failure_type=failure_type,
        regressions_only=regressions_only,
    )


@app.get("/api/v1/runs/{run_id}/comparison")
def get_comparison(run_id: str, db: Db) -> dict:
    return comparison_payload(_run_or_404(db, run_id))


@app.get("/api/v1/overview")
def overview(db: Db) -> dict:
    since = datetime.now(UTC) - timedelta(days=7)
    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.created_at >= since)
            .options(
                selectinload(ExperimentRun.case_results).selectinload(CaseResult.metrics),
                selectinload(ExperimentRun.experiment),
            )
            .order_by(ExperimentRun.created_at.desc())
        )
    )
    completed_attempts = sum(run.total for run in runs if run.status in {"completed", "completed_with_errors"})
    successful_attempts = sum(run.successful for run in runs if run.status in {"completed", "completed_with_errors"})
    p95_values = []
    all_costs = []
    for run in runs:
        latencies = sorted(row.latency_ms for row in run.case_results if row.latency_ms is not None)
        if latencies:
            p95_values.append(latencies[min(len(latencies) - 1, int((len(latencies) - 1) * 0.95))])
        all_costs.extend(row.cost_usd for row in run.case_results if row.cost_usd is not None)
    regression_watch = []
    regression_run_id = None
    for run in runs:
        if run.status not in {"completed", "completed_with_errors"}:
            continue
        payload = failure_payload(run, regressions_only=True)
        if payload["total"]:
            regression_watch = payload["items"]
            regression_run_id = run.id
            break
    return {
        "runs_this_week": len(runs),
        "success_rate": successful_attempts / completed_attempts if completed_attempts else None,
        "success_numerator": successful_attempts,
        "success_denominator": completed_attempts,
        "average_p95_latency_ms": sum(p95_values) / len(p95_values) if p95_values else None,
        "total_spend_usd": sum(all_costs) if all_costs else None,
        "datasets_registered": db.scalar(select(func.count()).select_from(Dataset)),
        "models_registered": db.scalar(select(func.count()).select_from(ModelConfig)),
        "recent_runs": [run_summary(run) for run in runs[:8]],
        "regression_watch": regression_watch,
        "regression_run_id": regression_run_id,
    }


@app.get("/api/v1/reports/{run_id}.md")
def markdown_report(run_id: str, db: Db) -> Response:
    report = generate_report(db, _run_or_404(db, run_id))
    return Response(
        report.markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.md"'},
    )


@app.get("/api/v1/reports/{run_id}.json")
def json_report(run_id: str, db: Db) -> dict:
    return generate_report(db, _run_or_404(db, run_id)).json_payload
