from __future__ import annotations

import os

import uvicorn

from app.main import app


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=max(1, int(os.getenv("WEB_CONCURRENCY", "2"))),
        timeout_keep_alive=int(os.getenv("UVICORN_KEEP_ALIVE", "30")),
    )
