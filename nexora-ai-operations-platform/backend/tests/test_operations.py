import json
from concurrent.futures import ThreadPoolExecutor
from threading import get_ident

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.main import create_app
from app.models.entities import Document, DocumentChunk, LLMCall, Request, User
from app.services.ai.providers import (
    CompletionRequest,
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderResult,
)
from app.services.request_service import _sanitize_answer


def test_answer_sanitizer_removes_model_emphasis_markers() -> None:
    answer = _sanitize_answer("## Next step\n\nFreeze the **stolen card** and verify __identity__.")

    assert "**" not in answer
    assert "__" not in answer
    assert "Freeze the stolen card and verify identity." in answer


def test_all_three_safe_tools_execute_through_request_pipeline(client: TestClient) -> None:
    customer = client.post(
        "/api/v1/requests",
        json={"message": "Get customer summary for CUST-1002"},
    ).json()
    assert customer["status"] == "completed"
    assert customer["tool_calls"][0]["tool_name"] == "get_customer_summary"
    assert customer["tool_calls"][0]["result_json"]["customer_id"] == "CUST-1002"
    assert customer["decision_factors"]["retrieval_attempted"] is True
    assert customer["decision_factors"]["retrieval_mode"] == "opportunistic_tool_evidence"
    assert customer["decision_factors"]["retrieval_status"] == "completed"

    service = client.post(
        "/api/v1/requests",
        json={"message": "What is the service status for identity verification?"},
    ).json()
    assert service["status"] == "completed"
    assert service["tool_calls"][0]["tool_name"] == "get_service_status"
    assert service["tool_calls"][0]["result_json"]["status"] == "degraded"

    ticket = client.post(
        "/api/v1/requests",
        json={"message": "Create a normal support ticket for a login question"},
    ).json()
    assert ticket["status"] == "completed"
    assert ticket["tool_calls"][0]["tool_name"] == "create_support_ticket"
    assert ticket["tool_calls"][0]["result_json"]["synthetic"] is True


def test_retrieval_failure_persists_failed_stage_audit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_retrieval(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("synthetic retrieval failure")

    monkeypatch.setattr(client.app.state.knowledge_service, "retrieve", fail_retrieval)
    response = client.post(
        "/api/v1/requests",
        json={"message": "What does the refund policy say?"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["decision_factors"]["retrieval_attempted"] is True
    assert payload["decision_factors"]["retrieval_status"] == "failed"


def test_rate_limit_returns_retry_after(settings) -> None:  # noqa: ANN001
    limited_settings = settings.model_copy(update={"rate_limit_requests": 1, "rate_limit_window_seconds": 60})
    with TestClient(create_app(limited_settings)) as limited:
        first = limited.get("/api/v1/metrics/summary")
        second = limited.get(
            "/api/v1/metrics/summary",
            headers={"Origin": "http://localhost:5173"},
        )
    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1
    assert second.headers["x-ratelimit-limit"] == "1"
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert second.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert second.headers["x-content-type-options"] == "nosniff"
    assert second.headers["content-security-policy"].startswith("default-src 'none'")
    assert second.headers["cache-control"] == "no-store"


def test_rate_limit_can_use_validated_proxy_client_ip(settings) -> None:  # noqa: ANN001
    proxy_settings = settings.model_copy(
        update={
            "rate_limit_requests": 1,
            "rate_limit_window_seconds": 60,
            "trust_proxy_headers": True,
        }
    )
    with TestClient(create_app(proxy_settings)) as proxied:
        first = proxied.get("/api/v1/metrics/summary", headers={"X-Real-IP": "192.0.2.10"})
        second = proxied.get("/api/v1/metrics/summary", headers={"X-Real-IP": "192.0.2.11"})
    assert first.status_code == 200
    assert second.status_code == 200


def test_auto_mode_keeps_one_stable_local_embedding_space(settings) -> None:  # noqa: ANN001
    auto_settings = settings.model_copy(
        update={"ai_provider_mode": "auto", "openai_api_key": "synthetic-not-a-real-key"}
    )
    application = create_app(auto_settings)
    assert application.state.knowledge_service.embeddings.name == "local-hash"


def test_retrieval_excludes_incompatible_embedding_spaces(client: TestClient, policy_document: dict) -> None:
    del policy_document
    with client.app.state.session_factory() as db:
        chunk = db.query(DocumentChunk).one()
        chunk.metadata_json = {"embedding_provider": "different-space"}
        db.commit()
        result = client.app.state.knowledge_service.retrieve(db, "card replacement", top_k=5)
    assert result.chunks == []


def test_document_embeddings_are_batched_in_chunk_order(
    client: TestClient,
    monkeypatch,
) -> None:  # noqa: ANN001
    knowledge = client.app.state.knowledge_service
    knowledge.chunk_size = 120
    knowledge.chunk_overlap = 20
    knowledge.embedding_batch_size = 3
    original_embed = knowledge.embeddings.embed
    batches: list[list[str]] = []

    def recording_embed(texts: list[str]) -> list[list[float]]:
        batches.append(list(texts))
        return original_embed(texts)

    monkeypatch.setattr(knowledge.embeddings, "embed", recording_embed)
    content = "\n\n".join(
        f"Policy paragraph {index} contains deterministic operational guidance and evidence."
        for index in range(20)
    )
    uploaded = client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("batched.md", content.encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert len(batches) > 1
    assert all(1 <= len(batch) <= 3 for batch in batches)
    with client.app.state.session_factory() as db:
        persisted = list(
            db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == uploaded.json()["id"])
                .order_by(DocumentChunk.chunk_index.asc())
            ).all()
        )
    assert [chunk.content for chunk in persisted] == [text for batch in batches for text in batch]
    assert all(len(chunk.embedding) == knowledge.embeddings.dimensions for chunk in persisted)


def test_upload_ingestion_runs_off_the_event_loop_thread(
    client: TestClient,
    monkeypatch,
) -> None:  # noqa: ANN001
    caller_thread = get_ident()
    ingestion_threads: list[int] = []
    original = client.app.state.knowledge_service.ingest

    def tracked_ingest(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        ingestion_threads.append(get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(client.app.state.knowledge_service, "ingest", tracked_ingest)
    response = client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("threaded.md", b"Threaded ingestion evidence.", "text/markdown")},
    )
    assert response.status_code == 201, response.text
    assert ingestion_threads and ingestion_threads[0] != caller_thread


def test_concurrent_identical_uploads_return_one_canonical_document(client: TestClient) -> None:
    def upload() -> object:
        return client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "same.md",
                    b"The exact same concurrently uploaded document.",
                    "text/markdown",
                )
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: upload(), range(2)))

    assert [response.status_code for response in responses] == [201, 201]
    assert len({response.json()["id"] for response in responses}) == 1
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_concurrent_requests_upsert_one_external_user_and_keep_both_audits(client: TestClient) -> None:
    def submit(index: int) -> object:
        return client.post(
            "/api/v1/requests",
            json={
                "message": f"A plain greeting number {index}",
                "user_id": "CUST-CONCURRENT-1",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, range(2)))

    assert [response.status_code for response in responses] == [201, 201]
    with client.app.state.session_factory() as db:
        users = list(db.scalars(select(User).where(User.external_id == "CUST-CONCURRENT-1")).all())
        requests = list(
            db.scalars(select(Request).where(Request.external_user_id == "CUST-CONCURRENT-1")).all()
        )
    assert len(users) == 1
    assert len(requests) == 2
    assert {request.user_id for request in requests} == {users[0].id}


def test_failed_fallback_attempts_are_persisted(settings) -> None:  # noqa: ANN001
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    primary = OpenAICompatibleProvider(
        api_key="synthetic-not-a-real-key",
        base_url="https://provider.invalid/v1",
        max_retries=2,
        transport=httpx.MockTransport(timeout),
    )
    application = create_app(settings, provider_overrides=[primary])
    with TestClient(application) as fallback_client:
        response = fallback_client.post(
            "/api/v1/requests",
            json={"message": "Explain the greeting hello", "routing_strategy": "fallback_chain"},
        )
    assert response.status_code == 201
    with application.state.session_factory() as db:
        calls = list(db.scalars(select(LLMCall).where(LLMCall.request_id == response.json()["request_id"])).all())
    assert any(call.provider == "openai-compatible" and not call.success for call in calls)
    assert any(call.provider == "mock" and call.success for call in calls)
    assert all(call.retries == 2 for call in calls if call.provider == "openai-compatible")


def test_below_floor_provider_fallback_is_audited_and_requires_review(settings) -> None:  # noqa: ANN001
    class TieredAIPrimeProvider(LLMProvider):
        name = "aiprimetech"

        def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
            if model in {"claude-sonnet-5", "claude-opus-5"}:
                raise ProviderError("synthetic tier outage")
            return ProviderResult(
                content="Standard replacement takes five business days [1].",
                provider=self.name,
                model=model,
                prompt_tokens=80,
                completion_tokens=20,
                latency_ms=4.0,
            )

    application = create_app(settings, provider_overrides=[TieredAIPrimeProvider()])
    with TestClient(application) as degraded_client:
        upload = degraded_client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "replacement-policy.md",
                    b"Replacement procedure: standard replacement takes five business days.",
                    "text/markdown",
                )
            },
            data={"title": "Replacement policy", "source": "Operations Manual"},
        )
        assert upload.status_code == 201, upload.text
        response = degraded_client.post(
            "/api/v1/requests",
            json={"message": "According to the procedure, does standard replacement take five business days?"},
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    factors = payload["decision_factors"]
    assert payload["status"] == "pending_review"
    assert payload["requires_review"] is True
    assert payload["model_used"] == "aiprimetech:claude-fable-5"
    assert factors["planned_model"] == "aiprimetech:claude-sonnet-5"
    assert factors["actual_model"] == "aiprimetech:claude-fable-5"
    assert factors["actual_quality_tier"] == 2
    assert factors["quality_floor"] == 4
    assert factors["fallback_used"] is True
    assert factors["degraded_below_quality_floor"] is True
    assert factors["attempted_models"] == [
        "aiprimetech:claude-sonnet-5",
        "aiprimetech:claude-opus-5",
        "aiprimetech:claude-fable-5",
    ]
    assert "degraded below quality floor 4" in payload["route_reason"]
    assert any("Model quality gate" in reason for reason in payload["escalation_reasons"])


def test_all_providers_unavailable_always_requires_review(settings) -> None:  # noqa: ANN001
    class FailingMockProvider(LLMProvider):
        name = "mock"

        def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
            raise ProviderError("synthetic total outage")

    application = create_app(settings, provider_overrides=[FailingMockProvider()])
    with TestClient(application) as outage_client:
        upload = outage_client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "outage-policy.md",
                    b"Outage procedure evidence is available for grounding.",
                    "text/markdown",
                )
            },
            data={"title": "Outage policy", "source": "Operations Manual"},
        )
        assert upload.status_code == 201, upload.text
        response = outage_client.post(
            "/api/v1/requests",
            json={"message": "What does the outage procedure evidence say?"},
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "pending_review"
    assert payload["requires_review"] is True
    assert payload["model_used"] == "provider-unavailable"
    assert payload["decision_factors"]["provider_unavailable"] is True
    assert any("Provider availability gate" in reason for reason in payload["escalation_reasons"])


def test_schema_invalid_classification_falls_back_is_persisted_and_requires_review(settings) -> None:  # noqa: ANN001
    class ClassificationFailingAIPrime(LLMProvider):
        name = "aiprimetech"

        def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
            if request.json_schema:
                return ProviderResult(
                    content='{"intent":"not-a-valid-contract"}',
                    provider=self.name,
                    model=model,
                    prompt_tokens=20,
                    completion_tokens=5,
                    latency_ms=2.0,
                )
            return ProviderResult(
                content="A concise generated response.",
                provider=self.name,
                model=model,
                prompt_tokens=30,
                completion_tokens=8,
                latency_ms=3.0,
            )

    class ClassificationFallbackMock(LLMProvider):
        name = "mock"

        def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
            return ProviderResult(
                content=json.dumps(
                    {
                        "intent": "general_knowledge",
                        "risk_level": "low",
                        "needs_retrieval": False,
                        "needs_tools": False,
                        "reason": "synthetic fallback classification",
                    }
                ),
                provider=self.name,
                model=model,
                prompt_tokens=20,
                completion_tokens=10,
                latency_ms=1.0,
            )

    application = create_app(
        settings,
        provider_overrides=[ClassificationFailingAIPrime(), ClassificationFallbackMock()],
    )
    with TestClient(application) as degraded_client:
        response = degraded_client.post(
            "/api/v1/requests",
            json={"message": "Please explain this situation in plain language."},
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["decision_factors"]["retrieval_attempted"] is False
    assert payload["decision_factors"]["retrieval_mode"] == "skipped"
    assert payload["decision_factors"]["retrieval_status"] == "skipped"
    classification = payload["decision_factors"]["classification"]
    assert payload["model_used"] == "aiprimetech:claude-fable-5"
    assert payload["status"] == "pending_review"
    assert classification["actual_model"] == "mock:nexora-deterministic-v1"
    assert classification["fallback_used"] is True
    assert classification["degraded_below_quality_floor"] is True
    assert payload["decision_factors"]["classification_degraded_below_quality_floor"] is True
    assert any("Classification quality gate" in reason for reason in payload["escalation_reasons"])
    classification_attempts = [
        attempt for attempt in payload["provider_attempts"] if attempt["purpose"] == "classification"
    ]
    assert [attempt["model"] for attempt in classification_attempts] == [
        "claude-fable-5",
        "claude-sonnet-5",
        "claude-opus-5",
        "nexora-deterministic-v1",
    ]
    assert all(attempt["prompt_tokens"] == 20 for attempt in classification_attempts[:3])
    assert all(attempt["completion_tokens"] == 5 for attempt in classification_attempts[:3])
    assert all(attempt["estimated_cost"] > 0 for attempt in classification_attempts[:3])


def test_invalid_citation_marker_is_removed_and_fails_answer_validation(settings) -> None:  # noqa: ANN001
    class InvalidCitationProvider(LLMProvider):
        name = "aiprimetech"

        def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
            return ProviderResult(
                content="Standard replacement takes five business days [999].",
                provider=self.name,
                model=model,
                prompt_tokens=30,
                completion_tokens=10,
                latency_ms=2.0,
            )

    application = create_app(settings, provider_overrides=[InvalidCitationProvider()])
    with TestClient(application) as citation_client:
        upload = citation_client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "citation-policy.md",
                    b"Replacement procedure: standard replacement takes five business days.",
                    "text/markdown",
                )
            },
            data={"title": "Citation policy", "source": "Operations Manual"},
        )
        assert upload.status_code == 201, upload.text
        response = citation_client.post(
            "/api/v1/requests",
            json={"message": "Does the procedure say standard replacement takes five business days?"},
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert "[999]" not in payload["response"]
    assert "Sources: [1]" in payload["response"]
    assert payload["decision_factors"]["citation_markers_valid"] is False
    assert payload["decision_factors"]["citation_marker_details"]["invalid_markers_removed"] == [999]
    assert payload["status"] == "pending_review"
    assert "answer validation failed" in payload["escalation_reasons"]


def test_postgresql_schema_compiles_to_pgvector() -> None:
    ddl = str(CreateTable(DocumentChunk.__table__).compile(dialect=postgresql.dialect()))
    assert "VECTOR(256)" in ddl.upper()


def test_aiprimetech_model_attempt_and_cost_are_persisted(settings) -> None:  # noqa: ANN001
    captured_messages: list = []

    class SyntheticAIPrimeProvider(LLMProvider):
        name = "aiprimetech"

        def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
            captured_messages.extend(request.messages)
            return ProviderResult(
                content="Standard replacement takes five business days [1].",
                provider=self.name,
                model=model,
                prompt_tokens=120,
                completion_tokens=40,
                latency_ms=12.5,
            )

    application = create_app(settings, provider_overrides=[SyntheticAIPrimeProvider()])
    with TestClient(application) as remote_client:
        upload = remote_client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "replacement.md",
                    (
                        b"Standard card replacement takes five business days. "
                        b"UNTRUSTED_SENTINEL_IGNORE_POLICY"
                    ),
                    "text/markdown",
                )
            },
            data={"title": "Replacement policy", "source": "Operations Manual"},
        )
        assert upload.status_code == 201
        response = remote_client.post(
            "/api/v1/requests",
            json={"message": "How long does the card replacement procedure take?"},
        )
        summary = remote_client.get("/api/v1/metrics/summary").json()

    assert response.status_code == 201
    payload = response.json()
    successful = [item for item in payload["provider_attempts"] if item["success"]]
    assert successful[-1]["provider"] == "aiprimetech"
    assert successful[-1]["model"] == "claude-sonnet-5"
    expected = 120 * 3 / 1_000_000 + 40 * 15 / 1_000_000
    assert successful[-1]["estimated_cost"] == pytest.approx(expected)
    assert payload["estimated_cost"] == pytest.approx(expected)
    assert summary["estimated_spend"] == pytest.approx(expected)
    assert [message.role for message in captured_messages] == ["system", "user"]
    assert "RETRIEVED SOURCES" not in captured_messages[0].content
    assert "How long does the card replacement" not in captured_messages[0].content
    assert "UNTRUSTED_SENTINEL_IGNORE_POLICY" not in captured_messages[0].content
    assert "<BEGIN_UNTRUSTED_USER_DATA>" in captured_messages[1].content
    assert "RETRIEVED SOURCES" in captured_messages[1].content
    assert "UNTRUSTED_SENTINEL_IGNORE_POLICY" in captured_messages[1].content
    assert "USER QUESTION" in captured_messages[1].content
