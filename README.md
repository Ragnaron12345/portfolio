# AI Engineering Portfolio

A showcase of 4 full-stack AI projects demonstrating practical skills in building, evaluating, and deploying AI-powered systems.

**Target roles:** AI Engineer Middle/Middle+ | System Analyst Junior+

---

## Quick Summary

| Project | What it does | Key Technologies |
|---------|-------------|-----------------|
| **Nexora** | AI customer support - routes requests, retrieves knowledge, executes safe actions | FastAPI, React, PostgreSQL, pgvector |
| **DocIntel** | Document processing - extracts data from PDFs/images, validates, routes to review | FastAPI, OCR, Pydantic, React |
| **EvalForge** | AI testing platform - compares models, prompts, measures quality | FastAPI, React, Recharts |
| **Flowline** | AI automation - processes invoices, incidents, support tickets | n8n, FastAPI, React, PostgreSQL |

---

## Project Highlights

### Nexora - AI Customer Support Platform
*AI-powered support system with human oversight*

- Routes customer requests to appropriate handling paths
- Retrieves answers from a knowledge base with citations
- Executes safe actions automatically; escalates risky ones
- Processes invoices via OCR and structured extraction
- 70 test cases with measurable quality metrics

**Stack:** FastAPI · React · TypeScript · PostgreSQL · pgvector · Docker

---

### DocIntel - Document Processing & Validation
*Extracts structured data from documents with quality controls*

- Uploads PDF, PNG, JPG → extracts text (native + OCR fallback)
- Classifies documents: invoice, bank statement, application
- Validates extracted data against business rules
- Routes unclear results to human review
- 64 test documents with measurable accuracy

**Stack:** FastAPI · React · TypeScript · PyMuPDF · Tesseract · Pydantic · PostgreSQL

---

### EvalForge - AI Testing & Validation Tool
*Reproducible benchmarking for AI systems*

- Compares LLM responses across models, prompts, configurations
- Measures quality, latency, cost, and safety
- Detects when improvements cause regressions
- Generates human-readable evaluation reports
- 56 test cases across multiple AI scenarios

**Stack:** FastAPI · React · TypeScript · Recharts · PostgreSQL · Docker

---

### Flowline - AI Automation Orchestration
*End-to-end automation with approval workflows*

- AI support triage with risk-based escalation
- Invoice processing with arithmetic validation
- Incident management with duplicate detection
- Human approval gates for sensitive operations
- Complete audit trails for all decisions

**Stack:** n8n · FastAPI · React · PostgreSQL · SQLAlchemy · Docker

---

## Technical Skills Demonstrated

### AI / ML
- LLM integration (OpenAI-compatible APIs)
- RAG (Retrieval-Augmented Generation)
- OCR and document classification
- Prompt engineering and evaluation
- Deterministic and LLM-based metrics

### Backend
- FastAPI with Pydantic v2 validation
- SQLAlchemy ORM (PostgreSQL, SQLite)
- Async task processing with bounded retries
- API design and documentation (OpenAPI)
- Vector search with pgvector

### Frontend
- React with TypeScript
- Professional data dashboards
- Charts and data visualization (Recharts)
- Responsive desktop-first UI

### DevOps / Infrastructure
- Docker and Docker Compose
- CI/CD workflows
- Environment configuration management

---

## Running the Projects

Each project runs locally with Docker:

```powershell
.\manage.ps1 Setup
.\manage.ps1 Up
```

All projects work offline with deterministic mock data - no external API keys required.

---

## Repository Structure

```
portfolio/
├── nexora-ai-operations-platform/      # AI customer support
├── document-intelligence-pipeline/      # Document processing
├── llm-evaluation-lab/                 # AI testing platform
└── ai-automation-pack/                 # Workflow automation
    ├── automation-api/                 # FastAPI backend
    ├── frontend/                       # React operator console
    ├── workflows/                      # n8n workflows
    └── docs/                           # Technical documentation
```
