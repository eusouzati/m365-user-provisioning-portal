from __future__ import annotations

from app.auth import Roles
from tests.conftest import principal_header

H = "X-MS-CLIENT-PRINCIPAL"


def test_busca_de_gestores(easyauth_client):
    h = principal_header(roles=(Roles.SOLICITANTE,))
    body = easyauth_client.get("/api/diretorio/usuarios?q=ana", headers={H: h}).json()
    assert body[0]["nome"] == "Ana Gestora"


def test_busca_exige_papel(easyauth_client):
    h = principal_header(roles=(Roles.APROVADOR,))
    assert easyauth_client.get("/api/diretorio/usuarios?q=ana", headers={H: h}).status_code == 403
    assert easyauth_client.get("/api/diretorio/usuarios?q=ana").status_code == 401


def test_busca_valida_tamanho(easyauth_client):
    h = principal_header(roles=(Roles.SOLICITANTE,))
    assert easyauth_client.get("/api/diretorio/usuarios?q=a", headers={H: h}).status_code == 422


def test_endereco_disponivel_e_conflitos(easyauth_client):
    h = principal_header(roles=(Roles.ADMINISTRADOR,))
    livre = easyauth_client.get(
        "/api/diretorio/endereco-disponivel?endereco=maria.nova@contoso.com", headers={H: h}
    ).json()
    assert livre["disponivel"] is True
    ocupado = easyauth_client.get(
        "/api/diretorio/endereco-disponivel?endereco=joao.silva@contoso.com", headers={H: h}
    ).json()
    assert ocupado["disponivel"] is False and ocupado["conflitos"][0]["tipo"] == "usuario"
    grupo = easyauth_client.get(
        "/api/diretorio/endereco-disponivel?endereco=allcompany@contoso.com", headers={H: h}
    ).json()
    assert grupo["disponivel"] is False and grupo["conflitos"][0]["tipo"] == "grupo"


def test_endereco_invalido(easyauth_client):
    h = principal_header(roles=(Roles.ADMINISTRADOR,))
    r = easyauth_client.get("/api/diretorio/endereco-disponivel?endereco=semarroba", headers={H: h})
    assert r.status_code == 422
