"""Fluxo HTTP: formulário → revisão → envio simulado (DRY_RUN)."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles
from app.core.profiles import GroupRef, OnboardingProfile
from app.main import create_app
from app.services.onboarding import today_in
from tests.conftest import make_settings, principal_header


@pytest.fixture
def rh(tmp_path) -> TestClient:
    s = make_settings(
        tmp_path,
        auth_mode="dev",
        dev_user_roles=Roles.SOLICITANTE,
        m365_default_domain="contoso.com",
    )
    app = create_app(s)
    app.state.storage.save_profile(
        OnboardingProfile(
            id="p-fin",
            nome="Financeiro — Funcionário",
            departamento="Financeiro",
            tipo_colaborador="funcionario",
            grupos_acesso=[GroupRef(id="g-fin", nome="Financeiro")],
            grupo_licenca=GroupRef(id="g-lic-e3", nome="Licença - Microsoft 365 E3"),
        )
    )
    return TestClient(app, follow_redirects=False)


def token(c):
    html = c.get("/solicitacoes/novo").text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def dados(c, **kw):
    admissao = today_in(c.app.state.settings) + timedelta(days=10)
    d = {
        "csrf_token": token(c),
        "nome": "João",
        "sobrenome": "da Silva",
        "matricula": "2001",
        "cargo": "Analista",
        "departamento": "Financeiro",
        "data_admissao": admissao.isoformat(),
        "gestor_id": "u-1",
        "gestor_nome": "Ana Gestora",
        "tipo_colaborador": "funcionario",
        "perfil_id": "p-fin",
        "pais": "Brasil",
    }
    d.update(kw)
    return d


def test_formulario_lista_perfis_ativos(rh):
    html = rh.get("/solicitacoes/novo").text
    assert "Financeiro — Funcionário" in html
    assert "js/gestor.js" in html


def test_revisao_mostra_upn_datas_e_grupos(rh):
    resp = rh.post("/solicitacoes/revisar", data=dados(rh))
    assert resp.status_code == 200
    html = resp.text
    assert "joao.silva2@contoso.com" in html
    assert "Ana Gestora" in html and "Financeiro" in html
    assert "Licença - Microsoft 365 E3" in html
    assert "DRY_RUN ativo" in html


def test_revisao_com_erros_volta_ao_formulario_preservando_dados(rh):
    resp = rh.post("/solicitacoes/revisar", data=dados(rh, nome="", gestor_id="u-999"))
    assert resp.status_code == 422
    assert "Nome: obrigatório." in resp.text
    assert 'value="da Silva"' in resp.text


def test_revisao_com_erro_de_negocio(rh):
    resp = rh.post("/solicitacoes/revisar", data=dados(rh, matricula="1001"))
    assert resp.status_code == 422 and "matrícula 1001" in resp.text


def test_envio_simulado_recalcula_e_nao_grava(rh):
    storage = rh.app.state.storage
    antes = storage.list_profiles()
    # Tentativa de adulterar o UPN pelo navegador é ignorada: o servidor recalcula.
    resp = rh.post("/solicitacoes/enviar", data=dados(rh, user_principal_name="ceo@contoso.com"))
    assert resp.status_code == 200
    assert "Nada foi gravado" in resp.text
    assert "joao.silva2@contoso.com" in resp.text and "ceo@contoso.com" not in resp.text
    assert storage.list_profiles() == antes


def test_envio_revalida(rh):
    resp = rh.post("/solicitacoes/enviar", data=dados(rh, perfil_id="p-inexistente"))
    assert resp.status_code == 422


def test_voltar_e_editar(rh):
    resp = rh.post("/solicitacoes/editar", data=dados(rh))
    assert resp.status_code == 200 and 'value="João"' in resp.text


def test_csrf_obrigatorio(rh):
    d = dados(rh)
    d.pop("csrf_token")
    assert rh.post("/solicitacoes/revisar", data=d).status_code == 403
    assert rh.post("/solicitacoes/enviar", data=d).status_code == 403


def test_somente_solicitante(easyauth_client):
    for papel in (Roles.APROVADOR, Roles.ADMINISTRADOR):
        h = principal_header(roles=(papel,))
        assert (
            easyauth_client.get(
                "/solicitacoes/novo", headers={"X-MS-CLIENT-PRINCIPAL": h}
            ).status_code
            == 403
        )
