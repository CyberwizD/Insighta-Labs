from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_base_url(value: str | None, default: str) -> str:
    raw = (value or default).strip()
    if "://" not in raw:
        scheme = "http" if raw.startswith(("127.0.0.1", "localhost")) else "https"
        raw = f"{scheme}://{raw}"
    parts = urlsplit(raw)
    scheme = parts.scheme or "https"
    netloc = parts.netloc or parts.path
    path = "" if parts.netloc else parts.path
    normalized = urlunsplit((scheme, netloc, path.rstrip("/"), "", ""))
    return normalized.rstrip("/")


@dataclass(slots=True)
class Settings:
    app_name: str
    app_base_url: str
    database_url: str
    secret_key: str
    github_client_id: str
    github_client_secret: str
    github_scope: str
    admin_usernames: set[str]
    enable_mock_github: bool
    access_token_ttl_minutes: int
    refresh_token_ttl_minutes: int
    access_cookie_name: str = "insighta_access_token"
    refresh_cookie_name: str = "insighta_refresh_token"
    csrf_cookie_name: str = "insighta_csrf_token"

    @property
    def github_callback_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/auth/github/callback"

    @property
    def mock_authorize_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/mock/github/authorize"


def get_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    default_db = f"sqlite:///{(root / 'insighta.db').as_posix()}"
    admin_usernames = {
        item.strip().lower()
        for item in os.getenv("INSIGHTA_ADMIN_USERNAMES", "admin").split(",")
        if item.strip()
    }
    return Settings(
        app_name="Insighta Labs+",
        app_base_url=_normalize_base_url(
            os.getenv("INSIGHTA_APP_BASE_URL"),
            "http://127.0.0.1:8000",
        ),
        database_url=os.getenv("INSIGHTA_DATABASE_URL", default_db),
        secret_key=os.getenv(
            "INSIGHTA_SECRET_KEY",
            "insighta-dev-secret-key-with-32-plus-bytes",
        ),
        github_client_id=os.getenv("INSIGHTA_GITHUB_CLIENT_ID", ""),
        github_client_secret=os.getenv("INSIGHTA_GITHUB_CLIENT_SECRET", ""),
        github_scope=os.getenv("INSIGHTA_GITHUB_SCOPE", "read:user user:email"),
        admin_usernames=admin_usernames,
        enable_mock_github=_as_bool(
            os.getenv("INSIGHTA_ENABLE_MOCK_GITHUB"), default=True
        ),
        access_token_ttl_minutes=int(
            os.getenv("INSIGHTA_ACCESS_TOKEN_TTL_MINUTES", "3")
        ),
        refresh_token_ttl_minutes=int(
            os.getenv("INSIGHTA_REFRESH_TOKEN_TTL_MINUTES", "5")
        ),
    )
