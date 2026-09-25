from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import SECURITY_HEADERS


def test_cabecalhos_de_seguranca(client):
    resp = client.get("/health")
    for name, value in SECURITY_HEADERS.items():
        assert resp.headers[name] == value


def test_docs_desabilitadas_por_padrao(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_nunca_em_producao(monkeypatch):
    class Falso:
        name = "falso"

        def ping(self) -> None:
            return None

    monkeypatch.setattr("app.main.build_storage", lambda _settings: Falso())
    s = Settings(
        _env_file=None,
        environment="production",
        azure_tenant_id="11111111-1111-1111-1111-111111111111",
        enable_api_docs=True,
        storage_backend="azure_table",
        azure_storage_table_endpoint="https://exemplo.table.core.windows.net",
    )
    client = TestClient(create_app(s))
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_pagina_inicial_em_portugues(client):  # modo dev: usuário simulado
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'lang="pt-BR"' in resp.text
    assert "Simulação" in resp.text
