"""Matriz de autenticação/autorização exigida no checkpoint da Sprint 2."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles, parse_client_principal
from app.main import create_app
from tests.conftest import OUTRO_TENANT, TENANT, make_settings, principal_header

H = "X-MS-CLIENT-PRINCIPAL"


# --- usuário sem autenticação -------------------------------------------------


def test_sem_autenticacao_redireciona_para_login(easyauth_client):
    resp = easyauth_client.get("/solicitacoes")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/.auth/login/aad?post_login_redirect_uri=/solicitacoes"


def test_sem_autenticacao_api_retorna_401(easyauth_client):
    assert easyauth_client.get("/api/me").status_code == 401


def test_health_continua_publico(easyauth_client):
    assert easyauth_client.get("/health").status_code == 200


# --- usuário de outro tenant ---------------------------------------------------


def test_outro_tenant_bloqueado(easyauth_client):
    h = principal_header(tid=OUTRO_TENANT, roles=(Roles.ADMINISTRADOR,))
    resp = easyauth_client.get("/admin", headers={H: h})
    assert resp.status_code == 403
    assert "outra organização" in resp.text


def test_outro_tenant_bloqueado_na_api(easyauth_client):
    h = principal_header(tid=OUTRO_TENANT)
    resp = easyauth_client.get("/api/me", headers={H: h})
    assert resp.status_code == 403
    assert resp.json() == {"erro": "tenant_nao_autorizado"}


def test_audiencia_errada_bloqueada(easyauth_client):
    h = principal_header(aud="99999999-9999-9999-9999-999999999999")
    assert easyauth_client.get("/api/me", headers={H: h}).status_code == 403


def test_provedor_diferente_de_aad_bloqueado(easyauth_client):
    h = principal_header()
    resp = easyauth_client.get("/api/me", headers={H: h, "X-MS-CLIENT-PRINCIPAL-IDP": "google"})
    assert resp.status_code == 403


# --- usuário autenticado sem papel --------------------------------------------


def test_autenticado_sem_papel_ve_inicio_mas_nao_areas(easyauth_client):
    h = principal_header(roles=())
    home = easyauth_client.get("/", headers={H: h})
    assert home.status_code == 200
    assert "ainda não possui papel" in home.text
    for rota in ("/solicitacoes", "/aprovacoes", "/admin"):
        assert easyauth_client.get(rota, headers={H: h}).status_code == 403


def test_papel_desconhecido_nao_concede_acesso(easyauth_client):
    h = principal_header(roles=("Provisionamento.SuperUsuario",))
    assert easyauth_client.get("/admin", headers={H: h}).status_code == 403


# --- usuário autenticado permitido --------------------------------------------


@pytest.mark.parametrize(
    ("papel", "permitidas", "negadas"),
    [
        (Roles.SOLICITANTE, ["/solicitacoes"], ["/aprovacoes", "/admin"]),
        (Roles.APROVADOR, ["/aprovacoes"], ["/solicitacoes", "/admin"]),
        (Roles.ADMINISTRADOR, ["/admin"], ["/solicitacoes", "/aprovacoes"]),
    ],
)
def test_matriz_de_papeis(easyauth_client, papel, permitidas, negadas):
    h = principal_header(roles=(papel,))
    for rota in permitidas:
        assert easyauth_client.get(rota, headers={H: h}).status_code == 200, rota
    for rota in negadas:
        assert easyauth_client.get(rota, headers={H: h}).status_code == 403, rota


def test_solicitante_nao_acessa_aprovacoes(easyauth_client):
    h = principal_header(roles=(Roles.SOLICITANTE,))
    assert easyauth_client.get("/aprovacoes", headers={H: h}).status_code == 403


def test_api_me(easyauth_client):
    h = principal_header(roles=(Roles.APROVADOR, "OutroPapelQualquer"))
    body = easyauth_client.get("/api/me", headers={H: h}).json()
    assert body["tenantId"] == TENANT
    assert body["roles"] == [Roles.APROVADOR]  # só papéis do portal


def test_menu_mostra_apenas_areas_do_papel(easyauth_client):
    h = principal_header(roles=(Roles.SOLICITANTE,))
    html = easyauth_client.get("/", headers={H: h}).text
    assert 'href="/solicitacoes"' in html
    assert 'href="/aprovacoes"' not in html
    assert 'href="/admin"' not in html
    assert "/.auth/logout" in html


# --- defesas contra cabeçalho forjado ------------------------------------------


def test_cabecalho_ignorado_sem_autenticacao_do_app_service(tmp_path):
    """Se o Easy Auth estiver desligado, o cabeçalho pode ser forjado: não confiar."""
    s = make_settings(tmp_path, auth_mode="easyauth", website_auth_enabled=False)
    c = TestClient(create_app(s), follow_redirects=False)
    h = principal_header(roles=(Roles.ADMINISTRADOR,))
    assert c.get("/api/me", headers={H: h}).status_code == 401
    assert c.get("/admin", headers={H: h}).status_code == 401


def test_cabecalho_invalido(easyauth_client):
    assert easyauth_client.get("/api/me", headers={H: "@@@"}).status_code == 401
    lixo = base64.b64encode(b'{"claims": "x"}').decode()
    assert easyauth_client.get("/api/me", headers={H: lixo}).status_code == 401


def test_claims_obrigatorias():
    import json

    sem_oid = base64.b64encode(
        json.dumps({"claims": [{"typ": "tid", "val": TENANT}]}).encode()
    ).decode()
    with pytest.raises(Exception, match="claims_obrigatorias_ausentes"):
        parse_client_principal(sem_oid)


def test_base64_sem_padding_aceito():
    h = principal_header().rstrip("=")
    assert parse_client_principal(h).tenant_id == TENANT


# --- modo desenvolvimento ------------------------------------------------------


def test_modo_dev_usa_papeis_configurados(tmp_path):
    s = make_settings(tmp_path, auth_mode="dev", dev_user_roles=Roles.APROVADOR)
    c = TestClient(create_app(s))
    assert c.get("/aprovacoes").status_code == 200
    assert c.get("/admin").status_code == 403
    assert "login simulado" in c.get("/").text
