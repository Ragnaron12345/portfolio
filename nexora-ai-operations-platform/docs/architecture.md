# Architecture

Nexora AI Operations Platform is designed as a production-oriented modular monolith: one FastAPI service owns the request workflow, while AI providers, retrieval, tools, review, evaluation, and persistence sit behind explicit interfaces. This document is the architecture contract. Runtime behavior remains authoritative and must be verified by tests and observable runs.

## System context

```mermaid
flowchart LR
    User[Customer or employee]
    Reviewer[Human reviewer]
    Operator[Knowledge or eval operator]
    UI[React dashboard]
    API[FastAPI service]
    DB[(PostgreSQL and pgvector)]
    LLM[LLM and embedding providers]
    Tools[Allowlisted business tools]

    User --> UI
    Reviewer --> UI
    Operator --> UI
    UI -->|JSON over /api/v1| API
    API --> DB
    API -->|provider adapters| LLM
    API -->|validated calls| Tools
```

The browser never receives provider credentials and does not call a model or business tool directly. PostgreSQL is the system of record; pgvector is an extension of the same persistence boundary rather than a separate source of truth.

## Backend module boundaries

| Boundary | Responsibility | Must not do |
| --- | --- | --- |
| `app.api` | HTTP routing, authentication context, request/response schemas, status codes | Contain prompts, SQL, provider-specific parsing, or business decisions |
| `app.schemas` | Pydantic v2 transport and structured-output contracts | Perform I/O or hide validation failures |
| `app.services.ai` | Deterministic/LLM classification, model registry and routing, provider adapters, fallback | Write HTTP responses or call unregistered tools |
| `app.services.rag` | Parse, chunk, embed, retrieve, rank, and construct citations | Treat retrieved text as trusted instructions |
| `app.services.tools` | Allowlist, Pydantic argument validation, tool execution, normalized results | Execute arbitrary code, shell commands, SQL, or unrestricted HTTP |
| `app.services.observability` | Trace context, structured events, latency/token/cost records, metric aggregation | Log secrets or use telemetry failure to change the business outcome |
| `app.services.evaluation` | Dataset loading, configuration execution, metric calculation, persisted run results | Publish invented or manually edited benchmark values |
| `app.models` and `app.db` | SQLAlchemy mappings, sessions, transactions, repository concerns | Depend on FastAPI request objects or provider SDK response types |
| workflow/orchestration service | Coordinate classification, retrieval/tools, routing, validation, review, and completion | Bypass validation or make provider-specific decisions |

Dependencies point inward toward schemas and service interfaces. Provider SDK objects are converted to internal results inside adapters. Database rows are converted to domain/transport models before leaving the backend.

## Request processing flow

```mermaid
flowchart TD
    A[POST /api/v1/requests] --> B[Validate input and assign trace_id]
    B --> C[Persist received request]
    C --> D[Intent and risk classifier]
    D --> E{Required path}
    E -->|knowledge| F[Retrieve evidence]
    E -->|approved action| G[Validate and invoke allowlisted tool]
    E -->|simple answer| H[Build response context]
    E -->|high risk or unsupported| R[Create review item]
    F --> I[Model router]
    G --> I
    H --> I
    I --> J[Provider adapter with fallback]
    J --> K[Structured validation and grounding checks]
    K --> L[Decision-score heuristic]
    L --> M{Safe to answer automatically?}
    M -->|yes| N[Persist response and metrics]
    M -->|no| R
    R --> O[Persist escalation reason and evidence]
    N --> P[Return response contract]
    O --> P
```

### Decision invariants

- Business `topic` (for example `card_security`) is independent from workflow
  `intent` and from `risk_level`; risk is never used as a topic label.
- `risk_level == high` always requires review, regardless of fluent model output.
- Missing evidence, incompatible current sources, invalid structured output, or a failed required tool prevents automatic completion.
- A tool call is possible only when its registered schema validates; a model-suggested tool name is not authority.
- Grounded paths may answer only from supplied evidence and must cite real retrieved chunks.
- “Confidence” is a workflow decision score, not a calibrated probability that the answer is true.
- Each provider attempt, fallback, retrieval, tool call, and terminal decision shares the same trace and request identifiers.

## Request sequence

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant API
    participant DB as PostgreSQL
    participant Classifier
    participant RAG
    participant Router
    participant Provider
    participant Validator

    Client->>API: POST request
    API->>DB: insert request and trace
    API->>Classifier: classify message
    Classifier-->>API: topic, intent, risk factors, retrieval/tools flags
    opt retrieval required
        API->>RAG: retrieve query with metadata filters
        RAG->>DB: vector or hybrid search
        DB-->>RAG: ranked chunks
        RAG-->>API: evidence and citations
    end
    API->>Router: select by purpose, intent, risk, complexity, and conflict
    Router->>Provider: structured generation
    alt provider succeeds
        Provider-->>Router: normalized result and usage
    else timeout or malformed result
        Router->>Provider: next configured fallback
        Provider-->>Router: normalized result or terminal error
    end
    Router-->>API: answer plus call records
    API->>Validator: grounding, structure, tool result, decision score
    Validator-->>API: automatic response or review reason
    API->>DB: persist terminal state and events
    API-->>Client: stable response schema
```

## Knowledge ingestion flow

```mermaid
flowchart LR
    U[Upload txt, md, or pdf] --> V[Size, MIME, extension, and filename validation]
    V --> S[Sanitized storage identity]
    S --> P[Format parser]
    P --> C[Deterministic chunker]
    C --> E[Embedding adapter]
    E --> T{All chunks valid?}
    T -->|yes| D[(documents and document_chunks)]
    T -->|no| X[Rollback and record safe error]
    D --> Q[Retrieval index available]
```

Parsing is a data boundary. Text such as “ignore previous instructions” remains quoted source content and never becomes a system or tool instruction. A document and its chunks become visible together; a partially embedded document is not retrieval-ready.

The document row stores normalized extracted content for full-document viewing.
Each chunk preserves `document_id`, title, source category, optional page
number, stable chunk index, content, embedding, character offsets/count, and
chunking metadata. The default chunker uses 900-character windows with
140-character overlap and prefers paragraph, sentence, then word boundaries.
Overlap prevents context loss at a boundary; hybrid retrieval combines 60%
semantic similarity and 40% keyword coverage. Citations are assembled from
persisted identifiers, not generated free-form by a model.

## Persistence model

```mermaid
erDiagram
    USERS ||--o{ REQUESTS : submits
    REQUESTS ||--o{ LLM_CALLS : records
    REQUESTS ||--o{ TOOL_CALLS : invokes
    REQUESTS ||--o| REVIEW_ITEMS : may_create
    DOCUMENTS ||--|{ DOCUMENT_CHUNKS : contains
    EVALUATION_RUNS ||--|{ EVALUATION_RESULTS : contains

    REQUESTS {
        uuid id PK
        uuid user_id FK
        string channel
        text message
        string intent
        string risk_level
        string status
        text response_text
        float confidence
        boolean requires_review
        datetime created_at
        datetime completed_at
    }
    LLM_CALLS {
        uuid id PK
        uuid request_id FK
        string provider
        string model
        string purpose
        int prompt_tokens
        int completion_tokens
        int latency_ms
        decimal estimated_cost
        boolean success
        text error
    }
    DOCUMENTS {
        uuid id PK
        string filename
        string title
        string source
        string mime_type
        json metadata_json
    }
    DOCUMENT_CHUNKS {
        uuid id PK
        uuid document_id FK
        int chunk_index
        text content
        int page_number
        vector embedding
        json metadata_json
    }
    TOOL_CALLS {
        uuid id PK
        uuid request_id FK
        string tool_name
        json arguments_json
        json result_json
        string status
        int latency_ms
    }
    REVIEW_ITEMS {
        uuid id PK
        uuid request_id FK
        string reason
        string status
        text reviewer_notes
        text edited_response
        datetime resolved_at
    }
```

Evaluation tables are deliberately separate from production request tables. A run stores its immutable configuration snapshot; each result stores the case ID, model, per-metric values, latency, estimated cost, pass state, and diagnostic details.

## Transaction and failure semantics

- Initial request persistence occurs before external AI work so a failure remains observable.
- Terminal request state and review creation are committed together where practical; duplicate review creation is prevented by request identity.
- Provider attempts and tool calls are recorded individually, including safe error categories. Secrets and raw credentials are never persisted.
- Provider timeout or malformed structured output moves through a bounded fallback chain. Exhaustion becomes a review/error outcome, not a fabricated answer.
- Ingestion uses one visibility boundary: failed parsing or embedding leaves no retrievable partial document.
- Evaluation failures are case results and do not erase earlier case results or rewrite benchmark history.

## Deployment topology

The required local topology is Docker Compose with frontend, backend, and PostgreSQL/pgvector containers. Redis may be introduced for rate limiting, caching, or background work, but the core request, review, and evaluation records remain durable in PostgreSQL. External paid providers are optional; the same service interfaces support a deterministic local/mock path for tests and demonstrations.

## Evolution rules

New providers, retrievers, or tools must implement an existing internal interface or introduce an explicit architecture decision. A feature is not documented as available until its API behavior, persistence, failure path, and test evidence exist.
