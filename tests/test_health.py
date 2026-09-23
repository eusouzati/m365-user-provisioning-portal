from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_retorna_healthy(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_ready_com_sqlite(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "storage": "sqlite"}


def test_ready_retorna_503_sem_vazar_erro(settings: Settings):
    app = create_app(settings)

    class Quebrado:
        name = "falso"

        def ping(self) -> None:
            raise RuntimeError("segredo-que-nao-pode-vazar")

    app.state.storage = Quebrado()
    resp = TestClient(app).get("/health/ready")
    assert resp.status_code == 503
    assert "segredo" not in resp.text
