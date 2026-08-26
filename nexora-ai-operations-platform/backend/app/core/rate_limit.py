from __future__ import annotations

import asyncio
import ipaddress
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """A small single-process limiter; replace with Redis for horizontal scale."""

    def __init__(
        self,
        app,
        *,
        limit: int,
        window_seconds: int,
        trust_proxy_headers: bool = False,
    ) -> None:  # noqa: ANN001
        super().__init__(app)
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self.trust_proxy_headers = trust_proxy_headers
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.endswith("/health"):
            return await call_next(request)
        key = self._client_key(request)
        now = time.monotonic()
        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
            bucket.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.limit - len(bucket)))
        return response

    def _client_key(self, request: Request) -> str:
        host = request.client.host if request.client else "unknown"
        if not self.trust_proxy_headers:
            return host
        candidate = request.headers.get("X-Real-IP", "").strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return host
