from __future__ import annotations

from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_optional_web_user,
    parse_optional_int,
    require_web_user,
    validate_web_csrf,
)
from app.api.web_support import template_context, templates
from app.config import get_settings
from app.database import get_db
from app.models import Profile, User
from app.services.auth import build_callback_url, revoke_refresh_token
from app.services.profiles import (
    build_list_query,
    paginate,
    search_profiles,
    serialize_profile,
)

settings = get_settings()
router = APIRouter(prefix="/web")


@router.get("/login", response_class=HTMLResponse)
def web_login(request: Request, db: Session = Depends(get_db)):
    user = get_optional_web_user(request, db)
    if user:
        return RedirectResponse("/web/dashboard")
    callback_url = build_callback_url(request)
    mock_query = urlencode(
        {
            "mode": "web",
            "provider": "mock",
            "redirect_uri": callback_url,
        }
    )
    return templates.TemplateResponse(
        request,
        "login.html",
        template_context(
            request,
            None,
            github_enabled=True,
            github_login_href="/auth/github?mode=web&provider=github",
            mock_enabled=settings.enable_mock_github,
            mock_login_href=f"/auth/github?{mock_query}",
        ),
    )


@router.get("/dashboard", response_class=HTMLResponse)
def web_dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_web_user(request, db)
    total_profiles = int(db.scalar(select(func.count()).select_from(Profile)) or 0)
    admin_count = int(
        db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
        or 0
    )
    analyst_count = int(
        db.scalar(select(func.count()).select_from(User).where(User.role == "analyst"))
        or 0
    )
    recent_profiles = db.scalars(
        select(Profile).order_by(Profile.created_at.desc()).limit(5)
    ).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        template_context(
            request,
            user,
            total_profiles=total_profiles,
            admin_count=admin_count,
            analyst_count=analyst_count,
            recent_profiles=[serialize_profile(profile) for profile in recent_profiles],
        ),
    )


@router.get("/profiles", response_class=HTMLResponse)
def web_profiles(
    request: Request,
    db: Session = Depends(get_db),
    gender: str | None = None,
    country: str | None = None,
    age_group: str | None = None,
    min_age: str | None = None,
    max_age: str | None = None,
    page: int = 1,
):
    user = require_web_user(request, db)
    parsed_min_age = parse_optional_int(min_age, "min_age")
    parsed_max_age = parse_optional_int(max_age, "max_age")
    stmt = build_list_query(
        gender=gender,
        country=country,
        age_group=age_group,
        min_age=parsed_min_age,
        max_age=parsed_max_age,
    )
    rows, total = paginate(db, stmt, page, 10)
    total_pages = ceil(total / 10) if total else 0
    return templates.TemplateResponse(
        request,
        "profiles.html",
        template_context(
            request,
            user,
            profiles=[serialize_profile(profile) for profile in rows],
            total=total,
            total_pages=total_pages,
            page=page,
            filters={
                "gender": gender or "",
                "country": country or "",
                "age_group": age_group or "",
                "min_age": parsed_min_age or "",
                "max_age": parsed_max_age or "",
            },
        ),
    )


@router.get("/profiles/{profile_id}", response_class=HTMLResponse)
def web_profile_detail(profile_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_web_user(request, db)
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return templates.TemplateResponse(
        request,
        "profile_detail.html",
        template_context(request, user, profile=serialize_profile(profile)),
    )


@router.get("/search", response_class=HTMLResponse)
def web_search(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = require_web_user(request, db)
    profiles = []
    total = 0
    error_message = ""
    if q.strip():
        try:
            rows, total = search_profiles(db, q, limit=20)
            profiles = [serialize_profile(profile) for profile in rows]
        except ValueError as exc:
            error_message = str(exc)
    return templates.TemplateResponse(
        request,
        "search.html",
        template_context(
            request,
            user,
            q=q,
            profiles=profiles,
            total=total,
            error_message=error_message,
        ),
    )


@router.get("/account", response_class=HTMLResponse)
def web_account(request: Request, db: Session = Depends(get_db)):
    user = require_web_user(request, db)
    return templates.TemplateResponse(
        request,
        "account.html",
        template_context(request, user),
    )


@router.post("/logout")
async def web_logout(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    validate_web_csrf(request, str(form.get("csrf_token", "")))
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token:
        revoke_refresh_token(db, refresh_token)
    response = RedirectResponse("/web/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(settings.access_cookie_name)
    response.delete_cookie(settings.refresh_cookie_name)
    response.delete_cookie(settings.csrf_cookie_name)
    return response
