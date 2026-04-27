from __future__ import annotations

import os

import uvicorn

from app.main import app


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        # Keep a single worker by default because rate limiting is process-local
        # and the default SQLite deployment is not intended for multi-worker writes.
        workers=max(1, int(os.getenv("WEB_CONCURRENCY", "1"))),
        timeout_keep_alive=int(os.getenv("UVICORN_KEEP_ALIVE", "30")),
    )
