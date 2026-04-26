from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401
    from app.services.profiles import COUNTRY_NAMES_BY_CODE

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as conn:
            if inspector.has_table("users"):
                user_columns = {col["name"] for col in inspector.get_columns("users")}
                if "email" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN email TEXT"))
                if "is_active" not in user_columns:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                        )
                    )
                if "last_login_at" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME"))
                conn.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))

            inspector = inspect(engine)
            if inspector.has_table("profiles"):
                profile_columns = {
                    col["name"] for col in inspector.get_columns("profiles")
                }
                if "country_name" not in profile_columns:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN country_name TEXT"))
                for code, name in COUNTRY_NAMES_BY_CODE.items():
                    conn.execute(
                        text(
                            "UPDATE profiles SET country_name = :name "
                            "WHERE country_id = :code AND (country_name IS NULL OR country_name = '')"
                        ),
                        {"name": name, "code": code},
                    )
