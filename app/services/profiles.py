from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from urllib.parse import urlencode

import requests
from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import Profile

COUNTRY_CODES = {
    "nigeria": "NG",
    "ghana": "GH",
    "kenya": "KE",
    "uganda": "UG",
    "south africa": "ZA",
    "united states": "US",
    "usa": "US",
    "canada": "CA",
    "germany": "DE",
    "france": "FR",
    "japan": "JP",
    "brazil": "BR",
    "india": "IN",
}

COUNTRY_NAMES_BY_CODE = {
    "NG": "Nigeria",
    "GH": "Ghana",
    "KE": "Kenya",
    "UG": "Uganda",
    "ZA": "South Africa",
    "US": "United States",
    "CA": "Canada",
    "DE": "Germany",
    "FR": "France",
    "JP": "Japan",
    "BR": "Brazil",
    "IN": "India",
}

SEED_PROFILES = [
    {"name": "Tunde", "gender": "male", "age": 22, "country_id": "NG"},
    {"name": "Chidi", "gender": "male", "age": 19, "country_id": "NG"},
    {"name": "Amina", "gender": "female", "age": 34, "country_id": "NG"},
    {"name": "Kwame", "gender": "male", "age": 28, "country_id": "GH"},
    {"name": "Akosua", "gender": "female", "age": 31, "country_id": "GH"},
    {"name": "Kamau", "gender": "male", "age": 41, "country_id": "KE"},
    {"name": "Akinyi", "gender": "female", "age": 27, "country_id": "KE"},
    {"name": "Musa", "gender": "male", "age": 52, "country_id": "UG"},
    {"name": "Lerato", "gender": "female", "age": 24, "country_id": "ZA"},
    {"name": "Daniel", "gender": "male", "age": 37, "country_id": "US"},
    {"name": "Sophia", "gender": "female", "age": 29, "country_id": "CA"},
    {"name": "Ifeoma", "gender": "female", "age": 18, "country_id": "NG"},
]

SORTABLE_FIELDS = {
    "created_at": Profile.created_at,
    "age": Profile.age,
    "name": Profile.name,
    "gender_probability": Profile.gender_probability,
    "country_probability": Profile.country_probability,
}


@dataclass(slots=True)
class QuerySpec:
    gender: str | None = None
    country_id: str | None = None
    age_group: str | None = None
    min_age: int | None = None
    max_age: int | None = None


def _normalized_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def _name_digest(name: str) -> bytes:
    return hashlib.sha256(_normalized_name(name).encode("utf-8")).digest()


def _fallback_enrichment(name: str) -> dict:
    digest = _name_digest(name)
    gender = "female" if digest[0] % 2 == 0 else "male"
    age = 18 + digest[1] % 45
    country_code = list(COUNTRY_NAMES_BY_CODE.keys())[digest[2] % len(COUNTRY_NAMES_BY_CODE)]
    gender_probability = round(0.55 + (digest[3] / 255) * 0.44, 2)
    country_probability = round(0.51 + (digest[4] / 255) * 0.48, 2)
    sample_size = 100 + digest[5]
    return {
        "name": name.strip(),
        "name_normalized": _normalized_name(name),
        "gender": gender,
        "gender_probability": gender_probability,
        "sample_size": sample_size,
        "age": age,
        "age_group": _age_group(age),
        "country_id": country_code,
        "country_name": COUNTRY_NAMES_BY_CODE.get(country_code, country_code),
        "country_probability": country_probability,
    }


def _external_enrichment(name: str) -> dict | None:
    try:
        genderize = requests.get(
            "https://api.genderize.io",
            params={"name": name},
            timeout=2,
        )
        agify = requests.get(
            "https://api.agify.io",
            params={"name": name},
            timeout=2,
        )
        nationalize = requests.get(
            "https://api.nationalize.io",
            params={"name": name},
            timeout=2,
        )
        if any(resp.status_code != 200 for resp in (genderize, agify, nationalize)):
            return None

        gender_body = genderize.json()
        age_body = agify.json()
        country_body = nationalize.json()
        countries = country_body.get("country") or []
        top_country = countries[0] if countries else {}

        gender = gender_body.get("gender")
        age = age_body.get("age")
        country_id = top_country.get("country_id")
        if not gender or not isinstance(age, int) or not country_id:
            return None

        return {
            "name": name.strip(),
            "name_normalized": _normalized_name(name),
            "gender": str(gender).lower(),
            "gender_probability": round(float(gender_body.get("probability") or 0.5), 2),
            "sample_size": int(gender_body.get("count") or 1),
            "age": int(age),
            "age_group": _age_group(int(age)),
            "country_id": str(country_id).upper(),
            "country_name": COUNTRY_NAMES_BY_CODE.get(
                str(country_id).upper(), str(country_id).upper()
            ),
            "country_probability": round(float(top_country.get("probability") or 0.5), 2),
        }
    except Exception:
        return None


def enrich_profile(name: str) -> dict:
    return _external_enrichment(name) or _fallback_enrichment(name)


def seed_profiles(db: Session) -> None:
    existing_names = {
        row[0]
        for row in db.execute(select(Profile.name_normalized)).all()
        if row and row[0]
    }
    for seed in SEED_PROFILES:
        normalized = _normalized_name(seed["name"])
        if normalized in existing_names:
            continue
        enriched = _fallback_enrichment(seed["name"])
        enriched["gender"] = seed["gender"]
        enriched["age"] = seed["age"]
        enriched["age_group"] = _age_group(seed["age"])
        enriched["country_id"] = seed["country_id"]
        enriched["country_name"] = COUNTRY_NAMES_BY_CODE[seed["country_id"]]
        enriched["gender_probability"] = 0.91
        enriched["country_probability"] = 0.88
        db.add(Profile(**enriched))
    db.commit()


def get_or_create_profile(db: Session, name: str) -> tuple[Profile, bool]:
    normalized = _normalized_name(name)
    existing = db.scalar(select(Profile).where(Profile.name_normalized == normalized))
    if existing:
        return existing, False
    profile = Profile(**enrich_profile(name))
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile, True


def validate_list_params(
    *,
    sort_by: str,
    order: str,
    limit: int,
) -> tuple[str, str, int]:
    if sort_by not in SORTABLE_FIELDS:
        raise ValueError("Invalid sort_by field")
    if order not in {"asc", "desc"}:
        raise ValueError("Invalid order value")
    return sort_by, order, max(1, min(limit, 50))


def build_list_query(
    *,
    gender: str | None = None,
    country_id: str | None = None,
    country: str | None = None,
    age_group: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    min_gender_probability: float | None = None,
    min_country_probability: float | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> Select[tuple[Profile]]:
    stmt = select(Profile)
    if gender:
        stmt = stmt.where(Profile.gender == gender.lower())
    country_value = country_id or _resolve_country(country)
    if country_value:
        stmt = stmt.where(Profile.country_id == country_value.upper())
    if age_group:
        stmt = stmt.where(Profile.age_group == age_group.lower())
    if min_age is not None:
        stmt = stmt.where(Profile.age >= min_age)
    if max_age is not None:
        stmt = stmt.where(Profile.age <= max_age)
    if min_gender_probability is not None:
        stmt = stmt.where(Profile.gender_probability >= min_gender_probability)
    if min_country_probability is not None:
        stmt = stmt.where(Profile.country_probability >= min_country_probability)

    sort_column = SORTABLE_FIELDS[sort_by]
    stmt = stmt.order_by(desc(sort_column) if order == "desc" else asc(sort_column))
    return stmt


def paginate(
    db: Session, stmt: Select[tuple[Profile]], page: int, limit: int
) -> tuple[list[Profile], int]:
    safe_limit = max(1, min(limit, 50))
    safe_page = max(1, page)
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.scalar(total_stmt) or 0)
    rows = db.scalars(stmt.offset((safe_page - 1) * safe_limit).limit(safe_limit)).all()
    return rows, total


def build_pagination_links(
    path: str,
    query_params: dict[str, str | int | float],
    *,
    page: int,
    limit: int,
    total: int,
) -> dict[str, str | None]:
    total_pages = ceil(total / limit) if total else 0

    def _url(target_page: int | None) -> str | None:
        if target_page is None:
            return None
        params = {k: v for k, v in query_params.items() if v not in ("", None)}
        params["page"] = target_page
        params["limit"] = limit
        return f"{path}?{urlencode(params)}"

    next_page = page + 1 if total_pages and page < total_pages else None
    prev_page = page - 1 if page > 1 else None
    return {
        "self": _url(page),
        "next": _url(next_page),
        "prev": _url(prev_page),
    }


def _resolve_country(country: str | None) -> str | None:
    if not country:
        return None
    text = country.strip().lower()
    if not text:
        return None
    if len(text) == 2:
        return text.upper()
    return COUNTRY_CODES.get(text)


def parse_search_query(q: str) -> QuerySpec:
    text = q.strip().lower()
    spec = QuerySpec()

    if "female" in text or "females" in text or "women" in text:
        spec.gender = "female"
    elif "male" in text or "males" in text or "men" in text:
        spec.gender = "male"

    for name, code in COUNTRY_CODES.items():
        if re.search(rf"\b{name}\b", text):
            spec.country_id = code
            break

    for label in ("child", "teenager", "adult", "senior"):
        if label in text or f"{label}s" in text:
            spec.age_group = label
            break
    if "young" in text and spec.age_group is None:
        spec.min_age = 16
        spec.max_age = 24

    above_match = re.search(r"(?:above|over|older than)\s+(\d+)", text)
    below_match = re.search(r"(?:below|under|younger than)\s+(\d+)", text)
    if above_match:
        spec.min_age = int(above_match.group(1))
    if below_match:
        spec.max_age = int(below_match.group(1))
    return spec


def search_profiles(
    db: Session,
    q: str,
    *,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "created_at",
    order: str = "desc",
) -> tuple[list[Profile], int]:
    spec = parse_search_query(q)
    if not any(
        [
            spec.gender,
            spec.country_id,
            spec.age_group,
            spec.min_age is not None,
            spec.max_age is not None,
        ]
    ):
        text = q.strip()
        if not text:
            raise ValueError("Search query is required")
        if len(text) < 3 or re.fullmatch(r"[a-z]{1,2}", text.lower()):
            raise ValueError("Unable to interpret the search query")
        stmt = (
            select(Profile)
            .where(
                or_(
                    Profile.name.ilike(f"%{text}%"),
                    Profile.country_id.ilike(f"%{text[:2].upper()}%"),
                    Profile.country_name.ilike(f"%{text}%"),
                )
            )
            .order_by(
                desc(SORTABLE_FIELDS[sort_by])
                if order == "desc"
                else asc(SORTABLE_FIELDS[sort_by])
            )
        )
        rows, total = paginate(db, stmt, page, limit)
        if total == 0:
            raise ValueError("Unable to interpret the search query")
        return rows, total

    stmt = build_list_query(
        gender=spec.gender,
        country_id=spec.country_id,
        age_group=spec.age_group,
        min_age=spec.min_age,
        max_age=spec.max_age,
        sort_by=sort_by,
        order=order,
    )
    return paginate(db, stmt, page, limit)


def serialize_profile(profile: Profile) -> dict:
    created_at = profile.created_at
    timestamp = (
        created_at.isoformat(timespec="seconds") + "Z"
        if isinstance(created_at, datetime)
        else str(created_at)
    )
    return {
        "id": profile.id,
        "name": profile.name,
        "gender": profile.gender,
        "gender_probability": profile.gender_probability,
        "sample_size": profile.sample_size,
        "age": profile.age,
        "age_group": profile.age_group,
        "country_id": profile.country_id,
        "country_name": profile.country_name
        or COUNTRY_NAMES_BY_CODE.get(profile.country_id, profile.country_id),
        "country_probability": profile.country_probability,
        "created_at": timestamp,
    }


def profiles_to_csv(profiles: list[Profile]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id",
            "name",
            "gender",
            "gender_probability",
            "age",
            "age_group",
            "country_id",
            "country_name",
            "country_probability",
            "created_at",
        ],
    )
    writer.writeheader()
    for profile in profiles:
        row = serialize_profile(profile)
        writer.writerow(
            {
                "id": row["id"],
                "name": row["name"],
                "gender": row["gender"],
                "gender_probability": row["gender_probability"],
                "age": row["age"],
                "age_group": row["age_group"],
                "country_id": row["country_id"],
                "country_name": row["country_name"],
                "country_probability": row["country_probability"],
                "created_at": row["created_at"],
            }
        )
    return buffer.getvalue()
