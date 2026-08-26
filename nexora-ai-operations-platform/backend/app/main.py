from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import InMemoryRateLimitMiddleware
from app.core.security import SecurityHeadersMiddleware
from app.db.init_db import initialize_schema
from app.db.session import build_engine, build_session_factory
from app.services.ai.classifier import IntentClassifier
from app.services.ai.orchestrator import build_ai_orchestrator
from app.services.ai.providers import LLMProvider
from app.services.evaluation.service import EvaluationService
from app.services.rag.embeddings import (
    LocalHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from app.services.rag.service import KnowledgeService
from app.services.request_service import PipelineServices, RequestProcessingService
from app.services.review_service import ReviewService
from app.services.tools.registry import SafeToolRegistry


def create_app(
    settings: Settings | None = None,
    *,
    provider_overrides: list[LLMProvider] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings.database_url)
    if settings.auto_create_schema:
        initialize_schema(engine)
    session_factory = build_session_factory(engine)

    local_embeddings = LocalHashEmbeddingProvider(settings.embedding_dimensions)
    if settings.ai_provider_mode == "openai" and settings.openai_api_key:
        # Embedding spaces cannot be mixed safely. Explicit OpenAI mode uses
        # only the remote embedding space; auto/mock use stable local vectors.
        embedding_provider = OpenAICompatibleEmbeddingProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.request_timeout_seconds,
        )
    else:
        embedding_provider = local_embeddings

    knowledge = KnowledgeService(
        embedding_provider,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        minimum_score=settings.retrieval_min_score,
        embedding_batch_size=settings.embedding_batch_size,
        max_document_chars=settings.max_document_chars,
        max_document_chunks=settings.max_document_chunks,
    )
    tools = SafeToolRegistry()
    ai = build_ai_orchestrator(settings, provider_overrides=provider_overrides)
    processor = RequestProcessingService(
        PipelineServices(
            settings=settings,
            ai=ai,
            knowledge=knowledge,
            tools=tools,
            classifier=IntentClassifier(),
        )
    )
    knowledge_mutation_lock = Lock()
    review_service = ReviewService(
        tools,
        claim_timeout_seconds=settings.review_claim_timeout_seconds,
    )
    evaluation_service = EvaluationService(
        processor,
        settings.eval_cases_file,
        held_out_cases_path=settings.eval_held_out_cases_file,
        knowledge_lock=knowledge_mutation_lock,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Only a process that actually starts serving the app owns this
        # recovery step. Import-only helpers (seed/export commands) construct
        # the global app but never enter its lifespan, so they cannot abandon
        # an evaluation that is live in the backend process.
        with session_factory() as startup_db:
            evaluation_service.reconcile_abandoned_runs(startup_db)
        yield
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Production-oriented API for grounded retrieval, model routing, allowlisted tools, "
            "human review, observability, and reproducible evaluations."
        ),
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.knowledge_service = knowledge
    app.state.request_processor = processor
    app.state.knowledge_mutation_lock = knowledge_mutation_lock
    app.state.review_service = review_service
    app.state.evaluation_service = evaluation_service

    # Starlette's last added middleware is outermost. Rate limiting must stay
    # inside security/CORS so its short-circuit 429 responses receive the same
    # browser and hardening headers as ordinary route responses.
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Trace-ID"],
        expose_headers=[
            "X-Trace-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-Evaluation-Run-ID",
            "Location",
            "Retry-After",
        ],
        max_age=600,
    )

    @app.middleware("http")
    async def request_trace(request: Request, call_next):  # noqa: ANN001, ANN202
        candidate = request.headers.get("X-Trace-ID", "")
        trace_id = candidate if len(candidate) <= 64 and candidate.isascii() else str(uuid4())
        if not trace_id:
            trace_id = str(uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response

    app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()


