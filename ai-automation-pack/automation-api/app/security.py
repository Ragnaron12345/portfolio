from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from fastapi import Header, HTTPException, Request, status

_INJECTION_PATTERNS = (
    re.compile(
        r"\bignore\s+(?:all\s+)?(?:previous|prior|your)\s+(?:instructions?|polic(?:y|ies))\b", re.IGNORECASE
    ),
    re.compile(r"\b(?:system|developer)\s+prompt\b", re.IGNORECASE),
    re.compile(r"\b(?:bypass|override|disable)\s+(?:safety|policy|guardrails?)\b", re.IGNORECASE),
    re.compile(r"\b(?:act|pretend)\s+as\s+(?:an?\s+)?(?:admin|system|developer)\b", re.IGNORECASE),
    re.compile(r"\bclose\s+(?:the\s+)?fraud\s+case\b", re.IGNORECASE),
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE = re.compile(r"\s+")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]{0,500}>")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = _CONTROL_CHARS.sub("", value)
    return _SPACE.sub(" ", value).strip()


def sanitize_text(value: str, *, max_length: int = 8_000) -> str:
    """Normalize untrusted text and remove markup while preserving readable operators.

    API strings are JSON data and React renders them as text, so HTML entity encoding
    here would be escaped a second time (for example, ``latency > 3s`` would appear as
    ``latency &gt; 3s``). Removing actual tags keeps stored text inert and readable.
    """

    normalized = normalize_text(value)
    return _HTML_TAG.sub("", normalized)[:max_length]


def detect_prompt_injection(value: str) -> tuple[bool, list[str]]:
    normalized = normalize_text(value)
    hits = [pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(normalized)]
    return bool(hits), hits


def sanitize_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            sanitize_text(str(key), max_length=100): sanitize_json(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [sanitize_json(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(str(value))


def redact_url(url: str | None) -> str | None:
    if not url:
        return None
    return "[configured]"


def require_internal_token(
    request: Request,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    expected = request.app.state.settings.internal_token.get_secret_value()
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


def stable_fingerprint(*parts: str) -> str:
    normalized = "|".join(normalize_text(part).casefold() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
