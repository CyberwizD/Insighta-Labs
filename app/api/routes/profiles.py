from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_user,
    parse_optional_float,
    parse_optional_int,
    read_json_body,
)
from app.api.responses import paginated_success, serialize_user, success
from app.database import get_db
from app.models import Profile, User
from app.services.auth import require_role
from app.services.profiles import (
    build_list_query,
    get_or_create_profile,
    paginate,
    profiles_to_csv,
    search_profiles,
    serialize_profile,
    validate_list_params,
)

router = APIRouter(prefix="/api")


@router.get("/users/me")
def users_me(current_user: User = Depends(get_current_user)):
    return success(serialize_user(current_user))


@router.get("/profiles")
def list_profiles(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    gender: str | None = None,
    country_id: str | None = None,
    country: str | None = None,
    age_group: str | None = None,
    min_age: str | None = None,
    max_age: str | None = None,
    min_gender_probability: str | None = None,
    min_country_probability: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 20,
):
    _ = current_user
    try:
        sort_by, order, limit = validate_list_params(
            sort_by=sort_by, order=order, limit=limit
        )
        parsed_min_age = parse_optional_int(min_age, "min_age")
        parsed_max_age = parse_optional_int(max_age, "max_age")
        parsed_min_gender_probability = parse_optional_float(
            min_gender_probability,
            "min_gender_probability",
        )
        parsed_min_country_probability = parse_optional_float(
            min_country_probability,
            "min_country_probability",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stmt = build_list_query(
        gender=gender,
        country_id=country_id,
        country=country,
        age_group=age_group,
        min_age=parsed_min_age,
        max_age=parsed_max_age,
        min_gender_probability=parsed_min_gender_probability,
        min_country_probability=parsed_min_country_probability,
        sort_by=sort_by,
        order=order,
    )
    rows, total = paginate(db, stmt, page, limit)
    return paginated_success(request, rows, page=page, limit=limit, total=total)


@router.get("/profiles/search")
def search_profile_endpoint(
    request: Request,
    q: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 20,
):
    _ = current_user
    try:
        sort_by, order, limit = validate_list_params(
            sort_by=sort_by, order=order, limit=limit
        )
        rows, total = search_profiles(
            db, q, page=page, limit=limit, sort_by=sort_by, order=order
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return paginated_success(request, rows, page=page, limit=limit, total=total)


@router.get("/profiles/export")
def export_profiles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    format: str = "csv",
    gender: str | None = None,
    country_id: str | None = None,
    country: str | None = None,
    age_group: str | None = None,
    min_age: str | None = None,
    max_age: str | None = None,
    min_gender_probability: str | None = None,
    min_country_probability: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
):
    _ = current_user
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only csv export is supported")
    try:
        sort_by, order, _ = validate_list_params(
            sort_by=sort_by, order=order, limit=50
        )
        parsed_min_age = parse_optional_int(min_age, "min_age")
        parsed_max_age = parse_optional_int(max_age, "max_age")
        parsed_min_gender_probability = parse_optional_float(
            min_gender_probability,
            "min_gender_probability",
        )
        parsed_min_country_probability = parse_optional_float(
            min_country_probability,
            "min_country_probability",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stmt = build_list_query(
        gender=gender,
        country_id=country_id,
        country=country,
        age_group=age_group,
        min_age=parsed_min_age,
        max_age=parsed_max_age,
        min_gender_probability=parsed_min_gender_probability,
        min_country_probability=parsed_min_country_probability,
        sort_by=sort_by,
        order=order,
    )
    rows = db.scalars(stmt).all()
    csv_content = profiles_to_csv(rows)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="profiles_{timestamp}.csv"'
        },
    )


@router.get("/profiles/{profile_id}")
def get_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return success(serialize_profile(profile))


@router.post("/profiles")
async def create_profile(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "admin")
    body = await read_json_body(request)
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    profile, created = get_or_create_profile(db, name)
    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return JSONResponse(
        status_code=status_code,
        content=success(
            serialize_profile(profile),
            message="Profile created" if created else "Profile already exists",
        ),
    )


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "admin")
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
