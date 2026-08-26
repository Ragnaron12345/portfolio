# Engineering Portfolio

A collection of production-oriented software and AI engineering projects. Each project lives in its own self-contained directory with source code, tests, documentation, and local setup instructions.

## Projects

### [Nexora AI Operations Platform](nexora-ai-operations-platform)

An AI operations platform for retrieval-augmented generation, explainable model routing, controlled tool execution, human review, observability, and repeatable LLM evaluation.

[![Nexora AI Operations Platform overview](nexora-ai-operations-platform/docs/images/nexora-overview.jpg)](nexora-ai-operations-platform)

**Stack:** FastAPI, React, TypeScript, PostgreSQL, pgvector, Docker Compose

**Highlights:** grounded RAG, risk-aware routing, schema-validated tools, review workflows, trace-level telemetry, typed document routing with native/OCR invoice extraction, plus checked-in 40-case regression and 30-case held-out evaluation evidence.

## Repository structure

```text
portfolio/
└── nexora-ai-operations-platform/
    ├── backend/
    ├── frontend/
    ├── docs/
    │   ├── api.md
    │   ├── architecture.md
    │   ├── evaluation.md
    │   └── security.md
    ├── docker-compose.yml
    └── README.md
```

Open a project directory for its complete documentation and startup instructions.
