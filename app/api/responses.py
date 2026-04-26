from __future__ import annotations

from math import ceil

from fastapi import Request
from fastapi.responses import JSONResponse

from app.models import Profile, User
from app.services.profiles import build_pagination_links, serialize_profile


def success(data=None, **extra):
    payload = {"status": "success"}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return payload


def error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message},
    )


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "github_id": user.github_id,
        "username": user.username,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() + "Z"
        if user.last_login_at
        else None,
        "created_at": user.created_at.isoformat() + "Z",
    }


def paginated_success(
    request: Request,
    rows: list[Profile],
    *,
    page: int,
    limit: int,
    total: int,
) -> dict:
    safe_page = max(page, 1)
    safe_limit = max(1, min(limit, 50))
    query_params = dict(request.query_params)
    total_pages = ceil(total / safe_limit) if total else 0
    return success(
        [serialize_profile(profile) for profile in rows],
        page=safe_page,
        limit=safe_limit,
        total=total,
        total_pages=total_pages,
        links=build_pagination_links(
            request.url.path,
            query_params,
            page=safe_page,
            limit=safe_limit,
            total=total,
        ),
    )
