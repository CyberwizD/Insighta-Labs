from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Request, Response
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.models import User

settings = get_settings()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def set_auth_cookies(response: Response, token_bundle: dict) -> None:
    response.set_cookie(
        settings.access_cookie_name,
        token_bundle["access_token"],
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        token_bundle["refresh_token"],
        httponly=True,
        samesite="lax",
    )


def ensure_csrf_cookie(response: Response, csrf_token: str | None = None) -> str:
    token = csrf_token or secrets.token_urlsafe(32)
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        httponly=False,
        samesite="lax",
    )
    return token


def template_context(request: Request, user: User | None, **extra) -> dict:
    return {
        "request": request,
        "user": user,
        "settings": settings,
        "csrf_token": request.cookies.get(settings.csrf_cookie_name, ""),
        **extra,
    }
