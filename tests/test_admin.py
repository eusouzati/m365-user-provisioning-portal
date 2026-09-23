"""Página de capacidades e CRUD de perfis (com CSRF e revalidação no backend)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles
from app.graph.errors import GraphPermissionError
from app.main import create_app
from tests.conftest import make_settings

H = "X-MS-CLIENT-PRINCIPAL"


@pytest.fixture
def admin(tmp_path) -> TestClient:
    s = make_settings(tmp_path, auth_mode="dev", dev_user_roles=Roles.ADMINISTRADOR)
    return TestClient(create_app(s), follow_redirects=False)


def csrf(client: TestClient, path="/admin/perfis/novo") -> str:
    html = client.get(path).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def novo(client, **extra):
    data = {
        "nome": "Financeiro — Funcionário",
        "departamento": "Financeiro",
        "tipo_colaborador": "funcionario",
        "grupos_acesso": ["g-fin", "g-vpn"],
        "grupo_licenca": "g-lic-e3",
        "ativo": "on",
        "csrf_token": csrf(client),
    }
    data.update(extra)
    return client.post("/admin/perfis", data=data)


# ------------------------------------------------------------ capacidades
def test_capacidades_mostra_tenant_licencas_e_grupos(admin):
    html = admin.get("/admin").text
    assert "Contoso (simulado)" in html
    assert "Microsoft 365 E3" in html and "SPE_E3" in html
    assert "papel do portal" in html  # grupo protegido sinalizado
    assert "funções administrativas" in html  # role-assignable sinalizado
    assert "DRY_RUN" in html


def test_capacidades_json(admin):
    body = admin.get("/admin/capacidades.json").json()
    assert body["capacidades"]["entra_p1"] is True
    assert body["licencas"][0]["disponiveis"] == 5
    assert body["dryRun"] is True


def test_capacidades_exige_admin(easyauth_client):
    from tests.conftest import principal_header

    h = principal_header(roles=(Roles.SOLICITANTE,))
    assert easyauth_client.get("/admin", headers={H: h}).status_code == 403
    assert easyauth_client.get("/admin/perfis", headers={H: h}).status_code == 403


def test_erro_de_permissao_no_graph(admin):
    graph = admin.app.state.graph

    def boom():
        raise GraphPermissionError("x", 403)

    graph.get_organization = boom
    resp = admin.get("/admin")
    assert resp.status_code == 503
    assert "Set-GraphPermissions.ps1" in resp.text


def test_cache_evita_chamadas_repetidas(admin):
    graph = admin.app.state.graph
    admin.get("/admin")
    admin.get("/admin")
    assert graph.calls.count("organization") == 1
    admin.get("/admin?refresh=true")
    assert graph.calls.count("organization") == 2


# --------------------------------------------------------------- perfis
def test_crud_de_perfil(admin):
    resp = novo(admin)
    assert resp.status_code == 303 and resp.headers["location"] == "/admin/perfis?ok=salvo"
    lista = admin.get("/admin/perfis").text
    assert "Financeiro — Funcionário" in lista and "VPN - Usuários" in lista

    perfil = admin.app.state.storage.list_profiles()[0]
    assert perfil.grupo_licenca.id == "g-lic-e3"
    assert perfil.atualizado_por  # quem alterou fica registrado

    token = csrf(admin, f"/admin/perfis/{perfil.id}")
    resp = admin.post(
        f"/admin/perfis/{perfil.id}",
        data={
            "nome": "Financeiro — Estagiário",
            "departamento": "Financeiro",
            "tipo_colaborador": "estagiario",
            "grupos_acesso": ["g-fin"],
            "csrf_token": token,
        },
    )
    assert resp.status_code == 303
    atualizado = admin.app.state.storage.get_profile(perfil.id)
    assert atualizado.tipo_colaborador == "estagiario" and atualizado.grupo_licenca is None
    assert atualizado.ativo is False  # checkbox desmarcado

    resp = admin.post(f"/admin/perfis/{perfil.id}/excluir", data={"csrf_token": token})
    assert resp.status_code == 303
    assert admin.app.state.storage.list_profiles() == []


def test_post_sem_csrf_bloqueado(admin):
    resp = admin.post(
        "/admin/perfis",
        data={"nome": "X perfil", "departamento": "x", "tipo_colaborador": "funcionario"},
    )
    assert resp.status_code == 403
    assert admin.app.state.storage.list_profiles() == []


def test_post_de_outra_origem_bloqueado(admin):
    resp = novo(admin, csrf_token=csrf(admin))
    assert resp.status_code == 303
    token = csrf(admin)
    resp = admin.post(
        "/admin/perfis",
        headers={"Origin": "https://evil.example"},
        data={
            "nome": "Outro perfil",
            "departamento": "x",
            "tipo_colaborador": "funcionario",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("grupo", ["g-portal-adm", "g-admins", "g-dyn", "inexistente"])
def test_ids_adulterados_sao_recusados(admin, grupo):
    resp = novo(admin, grupos_acesso=[grupo])
    assert resp.status_code == 422
    assert admin.app.state.storage.list_profiles() == []


def test_nome_duplicado(admin):
    assert novo(admin).status_code == 303
    resp = novo(admin)
    assert resp.status_code == 422 and "Já existe" in resp.text


def test_formulario_preserva_dados_em_erro(admin):
    resp = novo(admin, tipo_colaborador="")
    assert resp.status_code == 422
    assert "Selecione o tipo de colaborador" in resp.text
    assert 'value="Financeiro — Funcionário"' in resp.text


def test_formulario_nao_oferece_grupos_proibidos(admin):
    html = admin.get("/admin/perfis/novo").text
    assert 'value="g-fin"' in html
    for proibido in ("g-portal-adm", "g-admins", "g-dyn", "g-all"):
        assert f'value="{proibido}"' not in html


def test_cookie_csrf_httponly(admin):
    resp = admin.get("/admin/perfis/novo")
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
