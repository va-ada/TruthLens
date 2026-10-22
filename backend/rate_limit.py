"""
In-process sliding-window rate limiter, keyed by (bucket, client IP).

State lives in this process: run ONE uvicorn worker per container (see backend/main.py).
"""
import math
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Tuple

from fastapi import Request

from backend import config

WINDOW_S = 60.0


def _now() -> float:
    return time.monotonic()


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, key: str, limit: int) -> int:
        """Records a hit. Returns 0 if allowed, else seconds until the oldest hit leaves the window."""
        if limit <= 0:
            return 0
        now = _now()
        with self._lock:
            hits = self._hits.setdefault((bucket, key), deque())
            while hits and now - hits[0] >= WINDOW_S:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, math.ceil(WINDOW_S - (now - hits[0])))
            hits.append(now)
            # Drop idle keys so the dict cannot grow without bound
            if len(self._hits) > 10000:
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= WINDOW_S]:
                    del self._hits[k]
            return 0

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    """request.client.host, or the left-most X-Forwarded-For entry when TRUST_PROXY is on."""
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit_name: str) -> Callable:
    """FastAPI dependency; the limit is read from backend.config at call time so tests can change it."""
    def dependency(request: Request) -> None:
        retry_after = limiter.check(bucket, client_ip(request), int(getattr(config, limit_name)))
        if retry_after:
            raise RateLimited(retry_after)
    return dependency
