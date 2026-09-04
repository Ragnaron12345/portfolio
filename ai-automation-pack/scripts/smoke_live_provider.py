"""One-shot OpenAI provider smoke test; the credential stays in process memory only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation-api"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import AiCall  # noqa: E402


def main() -> None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is not present in this process.")

    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            internal_token="live-smoke-only",
            ai_provider="openai",
            ai_fallback_provider="none",
            openai_api_key=key,
            use_n8n=False,
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/classify",
            json={
                "text": "How long does a standard card replacement take?",
                "context": {"purpose": "credential-safe live smoke"},
            },
        )
        body = response.json()
        with app.state.database.session_factory() as db:
            call = db.scalar(select(AiCall).order_by(AiCall.created_at.desc()))

    result = {
        "http_status": response.status_code,
        "category": body.get("category"),
        "reason_present": bool(body.get("reason")),
        "confidence_basis_count": len(body.get("confidence_basis", [])),
        "provider": call.provider if call else None,
        "model": call.model if call else None,
        "input_tokens": call.input_tokens if call else None,
        "output_tokens": call.output_tokens if call else None,
        "estimated_cost_usd": str(call.estimated_cost_usd) if call else None,
        "success": call.success if call else False,
        "safe_error_code": (body.get("error") or {}).get("code"),
    }
    print(json.dumps(result, indent=2))
    if response.status_code != 200 or not call or not call.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
