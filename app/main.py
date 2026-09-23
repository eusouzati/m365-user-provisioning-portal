"""Ponto de entrada FastAPI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, get_settings
from app.observability import configure_observability
from app.routes import health, home
from app.security import SecurityHeadersMiddleware
from app.storage import build_storage

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_observability(settings)

    docs = settings.enable_api_docs and not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.storage = build_storage(settings)

    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(health.router)
    app.include_router(home.router)
    return app


app = create_app()
