from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, sqlite_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
