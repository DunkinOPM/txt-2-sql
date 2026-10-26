import time
import threading
from collections import defaultdict
from typing import Dict, List
from fastapi import Request, HTTPException, status
from app.core.config import settings


class InMemorySlidingWindowRateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter.
    Does not require Redis or external infrastructure.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = defaultdict(list)

    def check_rate_limit(self, key: str, max_requests: int, window_seconds: int = 60) -> None:
        if max_requests <= 0:
            return  # Rate limiting disabled

        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._records[key]
            # Prune timestamps outside current sliding window
            valid_timestamps = [t for t in timestamps if t > cutoff]
            if len(valid_timestamps) >= max_requests:
                # Do not record this blocked request; raise 429
                self._records[key] = valid_timestamps
                retry_after = int(valid_timestamps[0] - cutoff) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error_code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit exceeded. Maximum {max_requests} requests per minute allowed.",
                        "retry_after_seconds": max(1, retry_after)
                    },
                    headers={"Retry-After": str(max(1, retry_after))}
                )

            valid_timestamps.append(now)
            self._records[key] = valid_timestamps

    def reset(self):
        with self._lock:
            self._records.clear()


limiter = InMemorySlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    # Handle X-Forwarded-For if behind a proxy
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def rate_limit_auth(request: Request) -> None:
    ip = get_client_ip(request)
    limiter.check_rate_limit(
        key=f"auth:{ip}",
        max_requests=settings.rate_limit_auth_per_minute,
        window_seconds=60
    )


def rate_limit_upload(request: Request) -> None:
    ip = get_client_ip(request)
    limiter.check_rate_limit(
        key=f"upload:{ip}",
        max_requests=settings.rate_limit_upload_per_minute,
        window_seconds=60
    )
