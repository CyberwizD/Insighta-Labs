from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.services.auth import AuthError, current_user_from_request

settings = get_settings()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    try:
        return current_user_from_request(request, db)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def get_optional_web_user(request: Request, db: Session) -> User | None:
    try:
        return current_user_from_request(request, db)
    except AuthError:
        return None


def require_web_user(request: Request, db: Session) -> User:
    user = get_optional_web_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def read_json_body(request: Request) -> dict:
    if not request.headers.get("content-type", "").startswith("application/json"):
        return {}
    try:
        return await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc


def validate_web_csrf(request: Request, submitted_token: str | None) -> None:
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if not cookie_token or not submitted_token or submitted_token != cookie_token:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def _query_parsing_error(field_name: str, value: object, kind: str) -> HTTPException:
    if kind == "integer":
        return HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "int_parsing",
                    "loc": ["query", field_name],
                    "msg": "Input should be a valid integer, unable to parse string as an integer",
                    "input": value,
                }
            ],
        )
    return HTTPException(
        status_code=422,
        detail=[
            {
                "type": "float_parsing",
                "loc": ["query", field_name],
                "msg": "Input should be a valid number, unable to parse string as a number",
                "input": value,
            }
        ],
    )


def _parse_optional_number(
    value: str | int | float | None,
    field_name: str,
    *,
    caster: Callable[[str], int] | Callable[[str], float],
    kind: str,
) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return caster(text)
    except ValueError as exc:
        raise _query_parsing_error(field_name, value, kind) from exc


def parse_optional_int(value: str | int | None, field_name: str) -> int | None:
    return _parse_optional_number(
        value,
        field_name,
        caster=int,
        kind="integer",
    )


def parse_optional_float(value: str | float | None, field_name: str) -> float | None:
    return _parse_optional_number(
        value,
        field_name,
        caster=float,
        kind="float",
    )
