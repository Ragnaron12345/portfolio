from __future__ import annotations

import hashlib
import io

from PIL import Image

from app.models import Document


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buffer, "PNG")
    return buffer.getvalue()


def test_health_reports_upload_limit(client) -> None:  # noqa: ANN001
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["max_upload_bytes"] == 1024


def test_server_rejects_oversized_file_with_clear_message(client) -> None:  # noqa: ANN001
    response = client.post(
        "/api/v1/documents",
        files={"file": ("oversized.png", b"\x89PNG\r\n\x1a\n" + b"x" * 2000, "image/png")},
    )
    assert response.status_code == 413
    assert "configured" in response.json()["detail"]


def test_content_signature_is_enforced(client) -> None:  # noqa: ANN001
    response = client.post(
        "/api/v1/documents",
        files={"file": ("fake.pdf", png_bytes(), "application/pdf")},
    )
    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


def test_original_file_is_served_inline_and_can_be_same_origin_framed(client, db, settings) -> None:  # noqa: ANN001
    content = png_bytes()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    path = settings.storage_path / "preview.png"
    path.write_bytes(content)
    document = Document(
        filename="invoice-preview.png",
        safe_filename=path.name,
        mime_type="image/png",
        size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(path),
    )
    db.add(document)
    db.commit()

    response = client.get(f"/api/v1/documents/{document.id}/file")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert response.content == content


def test_non_preview_routes_remain_non_frameable(client) -> None:  # noqa: ANN001
    response = client.get("/api/v1/health")

    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
