from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import read_json_body, validate_web_csrf
from app.api.responses import success
from app.api.web_support import ensure_csrf_cookie, set_auth_cookies, templates
from app.config import get_settings
from app.database import get_db
from app.services.auth import (
    build_authorize_url,
    build_callback_url,
    create_mock_provider_code,
    exchange_github_code,
    generate_state,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    upsert_user,
)

settings = get_settings()
router = APIRouter()


@router.get("/auth/github")
def auth_github(
    request: Request,
    provider: Annotated[str, Query(pattern="^(auto|github|mock)$")] = "auto",
    mode: Annotated[str, Query(pattern="^(web|cli)$")] = "web",
    state: str | None = None,
    code_challenge: str | None = None,
    redirect_uri: str | None = None,
):
    issued_state = state or generate_state()
    redirect_uri = redirect_uri or build_callback_url(request)
    if mode == "web":
        response = RedirectResponse(
            build_authorize_url(
                provider=provider,
                mode=mode,
                state=issued_state,
                redirect_uri=redirect_uri,
            )
        )
        response.set_cookie(
            "insighta_oauth_state",
            issued_state,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            "insighta_oauth_redirect_uri",
            redirect_uri,
            httponly=True,
            samesite="lax",
        )
        return response

    if not code_challenge:
        raise HTTPException(
            status_code=400,
            detail="code_challenge is required for CLI mode",
        )
    return RedirectResponse(
        build_authorize_url(
            provider=provider,
            mode=mode,
            state=issued_state,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
        )
    )


@router.get("/auth/github/callback")
def auth_github_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    mode: str = "web",
    code_verifier: str | None = None,
    redirect_uri: str | None = None,
):
    if not code or not state:
        raise HTTPException(status_code=400, detail="Both code and state are required")

    expected_state = request.cookies.get("insighta_oauth_state")
    expected_redirect_uri = request.cookies.get("insighta_oauth_redirect_uri")
    if mode == "web":
        if not expected_state or expected_state != state:
            raise HTTPException(status_code=400, detail="Invalid state value")
    elif not code_verifier:
        raise HTTPException(
            status_code=400, detail="code_verifier is required for CLI mode"
        )

    identity = exchange_github_code(
        code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri or expected_redirect_uri or build_callback_url(request),
    )
    user = upsert_user(db, identity)
    token_bundle = issue_tokens(db, user)

    if mode == "cli":
        return token_bundle

    response = RedirectResponse("/web/dashboard", status_code=status.HTTP_302_FOUND)
    set_auth_cookies(response, token_bundle)
    ensure_csrf_cookie(response)
    response.delete_cookie("insighta_oauth_state")
    response.delete_cookie("insighta_oauth_redirect_uri")
    return response


@router.post("/auth/refresh")
async def refresh_auth(request: Request, db: Session = Depends(get_db)):
    body = await read_json_body(request)
    refresh_token = body.get("refresh_token") or request.cookies.get(
        settings.refresh_cookie_name
    )
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token is required")
    token_bundle = rotate_refresh_token(db, refresh_token)
    response = JSONResponse(token_bundle)
    set_auth_cookies(response, token_bundle)
    ensure_csrf_cookie(response, request.cookies.get(settings.csrf_cookie_name))
    return response


@router.post("/auth/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    body = await read_json_body(request)
    refresh_token = body.get("refresh_token") or request.cookies.get(
        settings.refresh_cookie_name
    )
    if refresh_token:
        revoke_refresh_token(db, refresh_token)
    response = JSONResponse(success(message="Logged out"))
    response.delete_cookie(settings.access_cookie_name)
    response.delete_cookie(settings.refresh_cookie_name)
    response.delete_cookie(settings.csrf_cookie_name)
    return response


@router.get("/mock/github/authorize", response_class=HTMLResponse)
def mock_github_authorize(
    request: Request,
    state: str,
    redirect_uri: str,
    mode: str = "web",
    username: str | None = None,
    role: str = "analyst",
):
    if not settings.enable_mock_github:
        raise HTTPException(status_code=404, detail="Mock auth is disabled")
    if username:
        code = create_mock_provider_code(username=username, role=role)
        target = f"{redirect_uri}?{urlencode({'code': code, 'state': state, 'mode': mode})}"
        return RedirectResponse(target)
    return templates.TemplateResponse(
        request,
        "mock_authorize.html",
        {
            "request": request,
            "state": state,
            "redirect_uri": redirect_uri,
            "mode": mode,
            "admin_query": urlencode(
                {
                    "state": state,
                    "redirect_uri": redirect_uri,
                    "mode": mode,
                    "username": "admin",
                    "role": "admin",
                }
            ),
            "analyst_query": urlencode(
                {
                    "state": state,
                    "redirect_uri": redirect_uri,
                    "mode": mode,
                    "username": "analyst",
                    "role": "analyst",
                }
            ),
            "guest_name": f"user-{generate_state()[:6]}",
        },
    )
