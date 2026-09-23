"""Fluxo HTTP completo: formulário → revisão → envio → aprovação/rejeição/cancelamento."""

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

H = "X-MS-CLIENT-PRINCIPAL"
RH = {
    H: principal_header(
        oid="aaaaaaaa-0000-0000-0000-000000000001", name="Rita RH", roles=(Roles.SOLICITANTE,)
    )
}
RH2 = {
    H: principal_header(
        oid="aaaaaaaa-0000-0000-0000-000000000002", name="Rui RH", roles=(Roles.SOLICITANTE,)
    )
}
TI = {
    H: principal_header(
        oid="bbbbbbbb-0000-0000-0000-000000000001", name="Tina TI", roles=(Roles.APROVADOR,)
    )
}
RH_E_TI = {
    H: principal_header(
        oid="cccccccc-0000-0000-0000-000000000001",
        name="Duda",
        roles=(Roles.SOLICITANTE, Roles.APROVADOR),
    )
}
ADM = {
    H: principal_header(
        oid="dddddddd-0000-0000-0000-000000000001", name="Adm", roles=(Roles.ADMINISTRADOR,)
    )
}


@pytest.fixture
def c(tmp_path) -> TestClient:
    s = make_settings(
        tmp_path, auth_mode="easyauth", website_auth_enabled=True, m365_default_domain="contoso.com"
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


def csrf(c, headers=RH):
    html = c.get("/solicitacoes/novo", headers=headers).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def dados(c, headers=RH, **kw):
    admissao = today_in(c.app.state.settings) + timedelta(days=10)
    d = {
        "csrf_token": csrf(c, headers),
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


def revisar(c, headers=RH, **kw):
    resp = c.post("/solicitacoes/revisar", data=dados(c, headers, **kw), headers=headers)
    assert resp.status_code == 200, resp.text
    return re.search(r'name="idem" value="([0-9a-f-]{36})"', resp.text).group(1)


def enviar(c, headers=RH, **kw) -> str:
    idem = kw.pop("idem", None) or revisar(c, headers, **kw)
    resp = c.post("/solicitacoes/enviar", data=dados(c, headers, idem=idem, **kw), headers=headers)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"].split("/")[-1].split("?")[0]


# ----------------------------------------------------------------- envio
def test_envio_grava_com_request_id(c):
    rid = enviar(c)
    assert re.fullmatch(r"REQ-\d{8}-0001", rid)
    req = c.app.state.storage.get_request(rid)
    assert req.status == "enviada"
    assert req.conta.user_principal_name == "joao.silva2@contoso.com"
    assert req.solicitante.nome == "Rita RH"
    assert req.historico[0].para == "enviada"
    html = c.get(f"/solicitacoes/{rid}?ok=enviada", headers=RH).text
    assert "aguarda aprovação" in html and "joao.silva2@contoso.com" in html


def test_duplo_clique_nao_duplica(c):
    idem = revisar(c)
    r1 = c.post("/solicitacoes/enviar", data=dados(c, idem=idem), headers=RH)
    r2 = c.post("/solicitacoes/enviar", data=dados(c, idem=idem), headers=RH)
    assert r1.status_code == r2.status_code == 303
    assert r2.headers["location"] == r1.headers["location"].split("?")[0]
    assert len(c.app.state.storage.list_requests()) == 1


def test_upn_adulterado_e_ignorado(c):
    rid = enviar(c, user_principal_name="ceo@contoso.com")
    assert c.app.state.storage.get_request(rid).conta.user_principal_name != "ceo@contoso.com"


def test_idem_invalido(c):
    resp = c.post("/solicitacoes/enviar", data=dados(c, idem="x"), headers=RH)
    assert resp.status_code == 422 and "expirou" in resp.text


def test_segunda_solicitacao_reserva_upn_e_matricula(c):
    enviar(c)
    idem = revisar(c, matricula="2002")
    rid2 = enviar(c, idem=idem, matricula="2002")
    assert (
        c.app.state.storage.get_request(rid2).conta.user_principal_name == "joao.silva3@contoso.com"
    )
    resp = c.post("/solicitacoes/revisar", data=dados(c, matricula="2001"), headers=RH)
    assert resp.status_code == 422 and "em andamento" in resp.text


def test_minhas_solicitacoes(c):
    rid = enviar(c)
    assert rid in c.get("/solicitacoes", headers=RH).text
    assert rid not in c.get("/solicitacoes", headers=RH2).text
    assert "1 solicitação(ões) em andamento" in c.get("/", headers=RH).text


def test_outro_solicitante_nao_ve_detalhe(c):
    rid = enviar(c)
    assert c.get(f"/solicitacoes/{rid}", headers=RH2).status_code == 403
    assert c.get(f"/solicitacoes/{rid}", headers=TI).status_code == 200
    assert c.get(f"/solicitacoes/{rid}", headers=ADM).status_code == 200
    assert c.get("/solicitacoes/REQ-19990101-0001", headers=TI).status_code == 404
    assert c.get("/solicitacoes/../../etc", headers=TI).status_code in (403, 404)


# ------------------------------------------------------------- aprovação
def test_fila_e_aprovacao(c):
    rid = enviar(c)
    fila = c.get("/aprovacoes", headers=TI).text
    assert rid in fila and "Aguardando aprovação (1)" in fila
    assert "1 solicitação(ões) aguardando sua aprovação" in c.get("/", headers=TI).text
    detalhe = c.get(f"/solicitacoes/{rid}", headers=TI).text
    assert "/aprovar" in detalhe and "/rejeitar" in detalhe

    resp = c.post(
        f"/aprovacoes/{rid}/aprovar",
        data={"csrf_token": csrf(c), "comentario": "ok, pode seguir"},
        headers=TI,
    )
    assert resp.status_code == 303
    req = c.app.state.storage.get_request(rid)
    assert req.status == "aprovada" and req.historico[-1].ator.nome == "Tina TI"
    assert "DRY_RUN" in c.get(f"/solicitacoes/{rid}?ok=aprovada", headers=TI).text


def test_solicitante_aprovador_nao_aprova_a_propria(c):
    rid = enviar(c, headers=RH_E_TI)
    detalhe = c.get(f"/solicitacoes/{rid}", headers=RH_E_TI).text
    assert "outro aprovador precisa decidir" in detalhe and "/aprovar" not in detalhe
    resp = c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=RH_E_TI)
    assert resp.status_code == 409
    assert c.app.state.storage.get_request(rid).status == "enviada"
    assert "aguardando sua aprovação" not in c.get("/", headers=RH_E_TI).text


def test_solicitante_puro_nao_acessa_aprovacao(c):
    rid = enviar(c)
    assert c.get("/aprovacoes", headers=RH).status_code == 403
    assert (
        c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=RH).status_code
        == 403
    )


def test_rejeicao_exige_comentario(c):
    rid = enviar(c)
    resp = c.post(
        f"/aprovacoes/{rid}/rejeitar", data={"csrf_token": csrf(c), "comentario": ""}, headers=TI
    )
    assert resp.status_code == 422 and "motivo" in resp.text
    resp = c.post(
        f"/aprovacoes/{rid}/rejeitar",
        data={"csrf_token": csrf(c), "comentario": "Cargo errado"},
        headers=TI,
    )
    assert resp.status_code == 303
    req = c.app.state.storage.get_request(rid)
    assert req.status == "rejeitada" and req.historico[-1].comentario == "Cargo errado"


def test_aprovacao_revalida_no_tenant(c):
    rid = enviar(c)
    # Depois do envio, o gestor foi desativado no diretório
    graph = c.app.state.graph
    graph.users = [
        u.__class__(**{**u.__dict__, "account_enabled": False}) if u.id == "u-1" else u
        for u in graph.users
    ]
    resp = c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI)
    assert resp.status_code == 422 and "desativada" in resp.text
    assert c.app.state.storage.get_request(rid).status == "enviada"


def test_aprovacao_atualiza_upn_se_ficou_indisponivel(c):
    rid = enviar(c)
    graph = c.app.state.graph
    u = graph.users[0]
    graph.users.append(
        u.__class__(
            id="u-9",
            display_name="Outro João",
            user_principal_name="joao.silva2@contoso.com",
            mail="joao.silva2@contoso.com",
        )
    )
    assert (
        c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI).status_code
        == 303
    )
    req = c.app.state.storage.get_request(rid)
    assert req.conta.user_principal_name == "joao.silva3@contoso.com"
    assert "UPN alterado" in req.historico[-1].comentario


def test_nao_decide_duas_vezes(c):
    rid = enviar(c)
    ok = c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI)
    assert ok.status_code == 303
    again = c.post(
        f"/aprovacoes/{rid}/rejeitar",
        data={"csrf_token": csrf(c), "comentario": "tarde demais"},
        headers=TI,
    )
    assert again.status_code == 422
    assert c.app.state.storage.get_request(rid).status == "aprovada"


# ----------------------------------------------------------- cancelamento
def test_cancelamento(c):
    rid = enviar(c)
    assert (
        c.post(
            f"/solicitacoes/{rid}/cancelar", data={"csrf_token": csrf(c)}, headers=TI
        ).status_code
        == 409
    )  # aprovador não cancela
    assert (
        c.post(
            f"/solicitacoes/{rid}/cancelar", data={"csrf_token": csrf(c)}, headers=RH
        ).status_code
        == 303
    )
    assert c.app.state.storage.get_request(rid).status == "cancelada"
    # cancelada libera UPN e matrícula
    rid2 = enviar(c)
    assert (
        c.app.state.storage.get_request(rid2).conta.user_principal_name == "joao.silva2@contoso.com"
    )


def test_admin_ve_todas(c):
    rid = enviar(c)
    html = c.get("/admin/solicitacoes", headers=ADM).text
    assert rid in html and "Rita RH" in html


def test_csrf_nas_decisoes(c):
    rid = enviar(c)
    assert c.post(f"/aprovacoes/{rid}/aprovar", data={}, headers=TI).status_code == 403
    assert c.post(f"/solicitacoes/{rid}/cancelar", data={}, headers=RH).status_code == 403
