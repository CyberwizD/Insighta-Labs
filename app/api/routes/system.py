from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import RedirectResponse

from app.api.responses import success

router = APIRouter()


@router.get("/")
def root():
    return RedirectResponse("/web/login", status_code=status.HTTP_302_FOUND)


@router.get("/health")
def health() -> dict:
    return success({"ok": True})
