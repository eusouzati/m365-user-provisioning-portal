from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.storage import StorageBackend


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> StorageBackend:
    return request.app.state.storage


def get_directory(request: Request):
    """Cache de leituras do Microsoft Graph (DirectoryCache)."""
    return request.app.state.directory


def get_graph(request: Request):
    """GraphService (somente leitura)."""
    return request.app.state.graph
