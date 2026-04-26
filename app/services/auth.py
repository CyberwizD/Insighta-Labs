from __future__ import annotations

import hashlib
import secrets
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlunsplit
from uuid import uuid4

import jwt
import requests
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefreshToken, User

settings = get_settings()


class AuthError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(status_code=status_code, detail=detail)


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def build_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return jwt.utils.base64url_encode(digest).decode("utf-8")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _encode_token(payload: dict[str, Any], expires_delta: timedelta) -> str:
    now = _utcnow()
    token_payload = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(token_payload, settings.secret_key, algorithm="HS256")


def create_access_token(user: User) -> str:
    return _encode_token(
        {
            "sub": user.id,
            "username": user.username,
            "role": user.role,
            "token_type": "access",
        },
        timedelta(minutes=settings.access_token_ttl_minutes),
    )


def create_refresh_token(db: Session, user: User) -> str:
    expires_delta = timedelta(minutes=settings.refresh_token_ttl_minutes)
    expires_at = _utcnow() + expires_delta
    jti = uuid4().hex
    token = _encode_token(
        {
            "sub": user.id,
            "jti": jti,
            "token_type": "refresh",
        },
        expires_delta,
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            expires_at=expires_at.replace(tzinfo=None),
        )
    )
    db.commit()
    return token


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid {expected_type} token") from exc

    token_type = payload.get("token_type")
    if token_type != expected_type:
        raise AuthError(f"Invalid {expected_type} token")
    return payload


def get_request_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        if token:
            return token
    cookie_token = request.cookies.get(settings.access_cookie_name)
    return cookie_token or None


def current_user_from_request(request: Request, db: Session) -> User:
    token = get_request_token(request)
    if not token:
        raise AuthError("Authentication required")

    payload = decode_token(token, "access")
    user = db.get(User, payload.get("sub"))
    if not user:
        raise AuthError("User not found")
    if not user.is_active:
        raise AuthError("User account is inactive", status.HTTP_403_FORBIDDEN)
    return user


def require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this endpoint",
        )


def issue_tokens(db: Session, user: User) -> dict[str, Any]:
    if not user.is_active:
        raise AuthError("User account is inactive", status.HTTP_403_FORBIDDEN)
    access_token = create_access_token(user)
    refresh_token = create_refresh_token(db, user)
    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "github_id": user.github_id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "avatar": user.avatar_url,
            "is_active": user.is_active,
        },
    }


def revoke_refresh_token(db: Session, refresh_token: str) -> None:
    payload = decode_token(refresh_token, "refresh")
    stmt = select(RefreshToken).where(RefreshToken.jti == payload.get("jti"))
    token_row = db.scalar(stmt)
    if token_row and token_row.revoked_at is None:
        token_row.revoked_at = datetime.utcnow()
        db.add(token_row)
        db.commit()


def rotate_refresh_token(db: Session, refresh_token: str) -> dict[str, Any]:
    payload = decode_token(refresh_token, "refresh")
    stmt = select(RefreshToken).where(RefreshToken.jti == payload.get("jti"))
    token_row = db.scalar(stmt)
    if not token_row or token_row.revoked_at is not None:
        raise AuthError("Refresh token has been revoked")
    if token_row.expires_at < datetime.utcnow():
        raise AuthError("Refresh token has expired")

    user = db.get(User, payload.get("sub"))
    if not user:
        raise AuthError("User not found")
    if not user.is_active:
        raise AuthError("User account is inactive", status.HTTP_403_FORBIDDEN)

    token_row.revoked_at = datetime.utcnow()
    db.add(token_row)
    db.commit()
    return issue_tokens(db, user)


def assign_role(username: str, preferred_role: str | None = None) -> str:
    if preferred_role in {"admin", "analyst"}:
        return preferred_role
    return "admin" if username.strip().lower() in settings.admin_usernames else "analyst"


def external_base_url(request: Request | None = None) -> str:
    if request is not None:
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_proto and forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
        url = request.url
        return urlunsplit((url.scheme, url.netloc, "", "", "")).rstrip("/")
    return settings.app_base_url


def build_callback_url(request: Request | None = None) -> str:
    return f"{external_base_url(request)}/auth/github/callback"


def build_authorize_url(
    *,
    provider: str,
    mode: str,
    state: str,
    redirect_uri: str,
    code_challenge: str | None = None,
) -> str:
    if provider == "auto":
        provider = "github"
    if provider == "mock":
        if not settings.enable_mock_github:
            raise AuthError("Mock auth is disabled", status.HTTP_404_NOT_FOUND)
        base_url = settings.mock_authorize_url
    elif provider == "github":
        base_url = "https://github.com/login/oauth/authorize"
    else:
        raise AuthError("Unsupported auth provider", status.HTTP_400_BAD_REQUEST)
    query = {
        "client_id": settings.github_client_id or "test-client-id",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": settings.github_scope,
        "state": state,
        "mode": mode,
    }
    if code_challenge:
        query["code_challenge"] = code_challenge
        query["code_challenge_method"] = "S256"
    return f"{base_url}?{urllib.parse.urlencode(query)}"


def _mock_code_payload(username: str, role: str) -> str:
    digest = hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()
    github_id = str(int(digest[:12], 16))
    email = f"{username.strip().lower().replace(' ', '.')}@mock.insighta.local"
    return jwt.encode(
        {
            "sub": github_id,
            "username": username,
            "email": email,
            "role": role,
            "avatar_url": f"https://avatars.githubusercontent.com/u/{github_id}?v=4",
            "token_type": "mock_code",
            "exp": int((_utcnow() + timedelta(minutes=10)).timestamp()),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def create_mock_provider_code(username: str, role: str) -> str:
    return _mock_code_payload(username=username, role=role)


def exchange_github_code(
    code: str,
    code_verifier: str | None = None,
    redirect_uri: str | None = None,
    username: str | None = None,
    preferred_role: str | None = None,
) -> dict[str, Any]:
    if code.startswith("test_code"):
        role = preferred_role if preferred_role in {"admin", "analyst"} else None
        lowered_code = code.lower()
        if role is None:
            if "admin" in lowered_code:
                role = "admin"
            elif "analyst" in lowered_code:
                role = "analyst"
        normalized_username = (username or "").strip().lower()
        if not normalized_username:
            normalized_username = "admin" if role == "admin" else "analyst"
        role = role or assign_role(normalized_username)
        github_id_source = f"test:{normalized_username}:{role}"
        github_id = str(int(hashlib.sha256(github_id_source.encode("utf-8")).hexdigest()[:12], 16))
        return {
            "github_id": github_id,
            "username": normalized_username,
            "email": f"{normalized_username}@example.com",
            "avatar_url": f"https://avatars.githubusercontent.com/u/{github_id}?v=4",
            "preferred_role": role,
        }

    try:
        payload = jwt.decode(code, settings.secret_key, algorithms=["HS256"])
        if payload.get("token_type") == "mock_code":
            return {
                "github_id": str(payload["sub"]),
                "username": payload["username"],
                "email": payload.get("email"),
                "avatar_url": payload.get("avatar_url"),
                "preferred_role": payload.get("role"),
            }
    except jwt.PyJWTError:
        pass

    if not settings.github_client_id or not settings.github_client_secret:
        raise AuthError(
            "GitHub OAuth is not configured. Enable mock auth or set GitHub credentials.",
            status.HTTP_400_BAD_REQUEST,
        )

    token_resp = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": redirect_uri or build_callback_url(),
            "code_verifier": code_verifier or "",
        },
        timeout=15,
    )
    token_resp.raise_for_status()
    token_body = token_resp.json()
    access_token = token_body.get("access_token")
    if not access_token:
        raise AuthError("GitHub token exchange failed", status.HTTP_400_BAD_REQUEST)

    user_resp = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    user_resp.raise_for_status()
    user_body = user_resp.json()
    email = user_body.get("email")
    if not email:
        email_resp = requests.get(
            "https://api.github.com/user/emails",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        )
        if email_resp.status_code == 200:
            for item in email_resp.json():
                if item.get("primary") and item.get("verified") and item.get("email"):
                    email = item["email"]
                    break
    return {
        "github_id": str(user_body["id"]),
        "username": user_body["login"],
        "email": email,
        "avatar_url": user_body.get("avatar_url"),
        "preferred_role": None,
    }


def upsert_user(db: Session, identity: dict[str, Any]) -> User:
    stmt = select(User).where(User.github_id == identity["github_id"])
    user = db.scalar(stmt)
    username = identity["username"]
    role = assign_role(username, identity.get("preferred_role"))
    if user is None:
        user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            github_id=identity["github_id"],
            username=username,
            email=identity.get("email"),
            avatar_url=identity.get("avatar_url"),
            role=role,
        )
    else:
        user.github_id = identity["github_id"]
        user.username = username
        user.email = identity.get("email")
        user.avatar_url = identity.get("avatar_url")
        user.role = role
    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
