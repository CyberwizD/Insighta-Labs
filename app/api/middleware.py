from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.responses import error
from app.http_runtime import client_ip, logger, rate_limiter, request_identity_key


def register_http_behavior(app: FastAPI) -> None:
    def apply_auth_cors_headers(request: Request, response):
        if request.url.path.startswith("/auth/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-API-Version"
            )
        return response

    @app.middleware("http")
    async def request_contracts(request: Request, call_next):
        started = time.perf_counter()

        if request.url.path.startswith("/api/"):
            if request.headers.get("X-API-Version") != "1":
                response = error("API version header required", status.HTTP_400_BAD_REQUEST)
                logger.info(
                    "%s %s %s %.2fms",
                    request.method,
                    request.url.path,
                    response.status_code,
                    (time.perf_counter() - started) * 1000,
                )
                return response

        if request.url.path.startswith("/auth/"):
            key = f"auth:{client_ip(request)}"
            if not rate_limiter.allow(key, limit=10):
                response = error("Rate limit exceeded", status.HTTP_429_TOO_MANY_REQUESTS)
                logger.info(
                    "%s %s %s %.2fms",
                    request.method,
                    request.url.path,
                    response.status_code,
                    (time.perf_counter() - started) * 1000,
                )
                return apply_auth_cors_headers(request, response)
        elif not request.url.path.startswith("/static/"):
            key = request_identity_key(request)
            if not rate_limiter.allow(f"app:{key}", limit=60):
                response = error("Rate limit exceeded", status.HTTP_429_TOO_MANY_REQUESTS)
                logger.info(
                    "%s %s %s %.2fms",
                    request.method,
                    request.url.path,
                    response.status_code,
                    (time.perf_counter() - started) * 1000,
                )
                return response

        response = await call_next(request)
        response = apply_auth_cors_headers(request, response)
        logger.info(
            "%s %s %s %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if request.url.path.startswith("/web/") and exc.status_code == 401:
            return apply_auth_cors_headers(
                request,
                RedirectResponse("/web/login", status_code=status.HTTP_302_FOUND),
            )
        if exc.status_code in {400, 401, 403, 404, 429}:
            return apply_auth_cors_headers(request, error(str(exc.detail), exc.status_code))
        return apply_auth_cors_headers(
            request,
            JSONResponse(
            status_code=exc.status_code,
            content={"status": "error", "message": str(exc.detail)},
            ),
        )
