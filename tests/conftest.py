from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TENANT = "11111111-1111-1111-1111-111111111111"
OUTRO_TENANT = "22222222-2222-2222-2222-222222222222"
CLIENT_ID = "33333333-3333-3333-3333-333333333333"


def make_settings(tmp_path, **overrides) -> Settings:
    base = {
        "_env_file": None,
        "sqlite_path": str(tmp_path / "test.db"),
        "azure_tenant_id": TENANT,
        "entra_app_client_id": CLIENT_ID,
        "graph_backend": "fake",
        "protected_group_ids": "g-portal-adm",
    }
    base.update(overrides)
    return Settings(**base)


def principal_header(
    *,
    tid: str = TENANT,
    oid: str = "44444444-4444-4444-4444-444444444444",
    name: str = "Maria Teste",
    roles: tuple[str, ...] = (),
    aud: str = CLIENT_ID,
) -> str:
    claims = [
        {"typ": "http://schemas.microsoft.com/identity/claims/tenantid", "val": tid},
        {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": oid},
        {"typ": "name", "val": name},
        {"typ": "preferred_username", "val": "maria@contoso.com"},
        {"typ": "aud", "val": aud},
        *({"typ": "roles", "val": r} for r in roles),
    ]
    payload = {
        "auth_typ": "aad",
        "claims": claims,
        "name_typ": "name",
        "role_typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path, auth_mode="dev")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def easyauth_client(tmp_path) -> TestClient:
    """Simula o App Service com autenticação ativa."""
    s = make_settings(tmp_path, auth_mode="easyauth", website_auth_enabled=True)
    return TestClient(create_app(s), follow_redirects=False)
