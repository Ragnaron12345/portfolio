from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    name: str
    model: str
    base_url: str | None
    dimensions: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic, dependency-free feature hashing for offline demos/tests."""

    name = "local-hash"
    model = "local-hash-blake2b-token-bigram-v1"
    base_url = None

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 32:
            raise ValueError("embedding dimensions must be at least 32")
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        normalized = text.casefold().replace("_", " ").replace("-", " ")
        tokens = re.findall(r"\w+", normalized, re.UNICODE)
        features = tokens + [f"{a}::{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for token in features:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            values[bucket] += sign
        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            values = [value / norm for value in values]
        return values


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int = 256,
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": texts, "dimensions": self.dimensions},
                )
            response.raise_for_status()
            data = response.json()["data"]
            ordered = sorted(data, key=lambda item: item["index"])
            vectors = [[float(value) for value in item["embedding"]] for item in ordered]
            if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
                raise KeyError("embedding count or dimensions do not match request")
            return vectors
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("embedding provider failed contract validation") from exc


class FallbackEmbeddingProvider(EmbeddingProvider):
    def __init__(self, primary: EmbeddingProvider, fallback: EmbeddingProvider) -> None:
        if primary.dimensions != fallback.dimensions:
            raise ValueError("embedding providers must use identical dimensions")
        self.primary = primary
        self.fallback = fallback
        self.dimensions = primary.dimensions
        self.name = f"{primary.name}-with-{fallback.name}-fallback"
        self.model = f"{primary.model}-with-{fallback.model}-fallback"
        self.base_url = primary.base_url

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self.primary.embed(texts)
        except EmbeddingError:
            return self.fallback.embed(texts)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator
