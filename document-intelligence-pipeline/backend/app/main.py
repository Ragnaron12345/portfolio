from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.config import get_settings
from app.db import create_schema
from app.seed_demo import seed_demo

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001, ANN201
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    create_schema()
    if settings.seed_demo:
        seed_demo()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # noqa: ANN201
    response = await call_next(request)
    is_document_preview = request.url.path.startswith(
        f"{settings.api_prefix}/documents/"
    ) and request.url.path.endswith("/file")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if is_document_preview else "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; frame-ancestors 'self'"
        if is_document_preview
        else "default-src 'none'; frame-ancestors 'none'"
    )
    return response


app.include_router(router, prefix=settings.api_prefix)
