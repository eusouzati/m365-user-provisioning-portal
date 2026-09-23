"""Ponto de entrada FastAPI.

Execução: ``uvicorn app.main:create_app --factory``
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, get_settings
from app.csrf import CsrfCookieMiddleware
from app.errors import register_error_handlers
from app.graph import build_graph
from app.graph.directory import DirectoryCache
from app.observability import configure_observability
from app.routes import admin, api, health, home, requests
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
    app.state.graph = build_graph(settings)
    app.state.directory = DirectoryCache(app.state.graph, settings.graph_cache_seconds)

    app.add_middleware(CsrfCookieMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(admin.router)
    app.include_router(requests.router)
    app.include_router(home.router)
    register_error_handlers(app)
    return app
