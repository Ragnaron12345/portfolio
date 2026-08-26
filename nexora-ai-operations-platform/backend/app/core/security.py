from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

ALLOWED_UPLOAD_EXTENSIONS: Final = {".txt", ".md", ".pdf"}
ALLOWED_UPLOAD_MIME_TYPES: Final = {
    "text/plain",
    "text/markdown",
    "application/pdf",
    "application/octet-stream",  # browsers do not always identify Markdown
}
UPLOAD_MIME_TYPES_BY_EXTENSION: Final = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
}

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(filename: str) -> str:
    """Strip path components and unsafe characters from an untrusted filename."""

    candidate = Path(filename.replace("\\", "/")).name
    candidate = _SAFE_FILENAME_RE.sub("_", candidate).strip(" .")
    if not candidate or candidate in {".", ".."}:
        raise ValueError("invalid filename")
    if Path(candidate).suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError("unsupported file type; use .txt, .md, or .pdf")
    return candidate[:240]


def upload_media_type_matches(filename: str, mime_type: str) -> bool:
    allowed = UPLOAD_MIME_TYPES_BY_EXTENSION.get(Path(filename).suffix.casefold(), set())
    return mime_type.casefold() in allowed


def looks_like_prompt_injection(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    patterns = (
        "ignore all previous",
        "ignore previous instructions",
        "ignore all policies",
        "reveal system prompt",
        "show me hidden system",
        "developer message",
        "print your instructions",
        "system override",
        "openai_api_key",
        "recovery codes",
        "just claim that",
        "jailbreak",
        "bypass safety",
    )
    if any(pattern in normalized for pattern in patterns):
        return True
    # Match common paraphrases without relying on one brittle exact phrase.
    # Distances are bounded to avoid a broad regex or pathological backtracking.
    paraphrases = (
        r"\bignore\b.{0,40}\b(?:all|previous|prior|earlier)\b.{0,40}"
        r"\b(?:instructions?|prompts?|polic(?:y|ies)|rules?)\b",
        r"\b(?:reveal|show|print|expose|repeat)\b.{0,40}"
        r"\b(?:hidden|system|developer|internal)\b.{0,30}"
        r"\b(?:prompts?|instructions?|messages?)\b",
    )
    return any(re.search(pattern, normalized) for pattern in paraphrases)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.endswith("/docs") or "/docs/" in request.url.path:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response
