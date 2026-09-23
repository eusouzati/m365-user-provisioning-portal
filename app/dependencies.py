from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.storage import StorageBackend


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> StorageBackend:
    return request.app.state.storage
