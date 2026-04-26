from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.ids import uuid7_str


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7_str)
    github_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("name_normalized", name="uq_profiles_name_norm"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7_str)
    name: Mapped[str] = mapped_column(String(120), index=True)
    name_normalized: Mapped[str] = mapped_column(String(120), index=True)
    gender: Mapped[str] = mapped_column(String(20), index=True)
    gender_probability: Mapped[float] = mapped_column()
    sample_size: Mapped[int] = mapped_column(Integer)
    age: Mapped[int] = mapped_column(Integer, index=True)
    age_group: Mapped[str] = mapped_column(String(20), index=True)
    country_id: Mapped[str] = mapped_column(String(2), index=True)
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_probability: Mapped[float] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
