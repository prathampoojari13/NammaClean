"""
In-memory sliding-window rate limiting dependency for FastAPI.
Provides DoS and brute-force protection without external dependencies (no Redis required).
"""

import time
import asyncio
from collections import defaultdict, deque
from typing import Dict, Deque, Optional
from fastapi import Request, HTTPException, status


def get_client_ip(request: Request) -> str:
    """
    Extracts the client IP address from the request.
    Inspects standard X-Forwarded-For header before falling back to request.client.host.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP address in the chain (the original client)
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


class RateLimiter:
    """
    Thread-safe and async-safe sliding-window rate limiter for FastAPI routes.

    Parameters:
    - max_requests: Maximum allowed requests within the time window.
    - window_seconds: Duration of the sliding time window in seconds.
    - key_prefix: Optional string prefix to namespace different limiters sharing client IPs.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        key_prefix: str = "",
    ):
        if max_requests <= 0:
            raise ValueError("max_requests must be greater than 0.")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0.")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self._history: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

    def _cleanup_stale_entries(self, now: float) -> None:
        """Periodically removes empty deques and stale IP entries to prevent memory leaks."""
        if now - self._last_cleanup < 300:  # Run cleanup at most once every 5 minutes
            return

        stale_keys = []
        for key, timestamps in self._history.items():
            while timestamps and timestamps[0] <= now - self.window_seconds:
                timestamps.popleft()
            if not timestamps:
                stale_keys.append(key)

        for key in stale_keys:
            self._history.pop(key, None)

        self._last_cleanup = now

    async def __call__(self, request: Request) -> None:
        """
        FastAPI dependency callable. Evaluates sliding window for caller IP.
        Raises HTTP 429 Too Many Requests if rate limit is exceeded.
        """
        client_ip = get_client_ip(request)
        key = f"{self.key_prefix}:{client_ip}" if self.key_prefix else client_ip
        now = time.time()

        async with self._lock:
            self._cleanup_stale_entries(now)
            timestamps = self._history[key]

            # Evict timestamps outside the sliding window
            cutoff = now - self.window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            # Check if limit is reached
            if len(timestamps) >= self.max_requests:
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + self.window_seconds - now) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                    headers={"Retry-After": str(retry_after)},
                )

            # Record current request timestamp
            timestamps.append(now)

    def reset(self) -> None:
        """Clears all tracking history. Used for unit testing."""
        self._history.clear()
        self._last_cleanup = time.time()
