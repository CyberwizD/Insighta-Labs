from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock

import jwt
from fastapi import Request

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("insighta.http")


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


rate_limiter = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    cf_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cf_ip:
        return cf_ip
    return request.client.host if request.client else "unknown"


def request_identity_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
    if not token:
        token = request.cookies.get(settings.access_cookie_name, "")

    if token:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
            subject = payload.get("sub")
            if subject:
                return f"user:{subject}"
        except jwt.PyJWTError:
            pass

    return f"ip:{client_ip(request)}"
