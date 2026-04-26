from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.middleware import register_http_behavior
from app.api.routes.auth import router as auth_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.system import router as system_router
from app.api.routes.web import router as web_router
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.services.profiles import seed_profiles

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).resolve().parent / "static"),
        name="static",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_http_behavior(app)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(profiles_router)
    app.include_router(web_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        with SessionLocal() as db:
            seed_profiles(db)

    return app


app = create_app()
