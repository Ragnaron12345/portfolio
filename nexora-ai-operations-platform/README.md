# Nexora - AI Customer Support Platform

An AI-powered customer support system with semantic knowledge retrieval, safe tool execution, and human oversight for sensitive operations.

![Nexora operations overview](docs/images/nexora-overview.jpg)

**What it demonstrates:** Building production-ready AI systems with proper safety controls - not just demos, but systems that know when to escalate to humans.

---

## Key Features

- **Intelligent routing** - classifies requests by intent, topic, and risk level
- **Knowledge retrieval** - finds relevant answers with source citations
- **Safe tool execution** - executes only allowlisted actions with validation
- **Human review workflow** - escalates risky or uncertain requests
- **Invoice processing** - OCR and structured extraction from uploaded documents
- **70 test cases** - regression and held-out evaluation sets

---

## Safety-First Design

```
Customer Request → Classify Risk → Safe Actions Only
                                         ↓
                    High Risk? → Human Approval → Execute
                                         ↓
                              Low Risk? → Auto-Execute → Done
```

**Risk categories:** low, medium, high - with different handling paths.

---

## What Makes It Different

- Every AI decision is grounded in retrieved knowledge
- Citations show exactly where answers come from
- Uncertain responses route to review, not hallucination
- Tool calls are validated against strict schemas
- Complete audit trail of all decisions

---

## Quick Start

```powershell
.\manage.ps1 Setup
.\manage.ps1 Up
.\manage.ps1 Seed  # Load demo cases
```

- UI: http://localhost:3000
- API: http://localhost:3000/api/v1/docs

---

## Architecture

```
React UI → FastAPI → PostgreSQL + pgvector
                  ↓
           Request Classifier → RAG Retrieval
                  ↓
           Tool Validator → Response Generator
                  ↓
           Safe Actions OR Human Review
```

**Stack:** FastAPI · React · TypeScript · PostgreSQL · pgvector · Docker

---

## License

MIT
