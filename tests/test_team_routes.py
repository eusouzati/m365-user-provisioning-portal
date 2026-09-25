"""Gestor gera o TAP; agendador chama o ciclo de vida com App Role de aplicação."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles
from app.core.profiles import GroupRef, OnboardingProfile
from app.graph.models import TapPolicy
from app.main import create_app
from app.services.onboarding import today_in
from tests.conftest import make_settings, principal_header
from tests.test_requests_routes import ADM, RH, TI, csrf, dados

H = "X-MS-CLIENT-PRINCIPAL"
GESTOR_OID = "u-1"  # Ana Gestora no Graph simulado
GESTORA = {H: principal_header(oid=GESTOR_OID, name="Ana Gestora")}
OUTRO = {H: principal_header(oid="u-2", name="Bruno")}
AGENDADOR = {H: principal_header(oid="mi-agendador", name="", roles=(Roles.AGENDADOR,))}


@pytest.fixture
def c(tmp_path) -> TestClient:
    s = make_settings(
        tmp_path,
        auth_mode="easyauth",
        website_auth_enabled=True,
        m365_default_domain="contoso.com",
        dry_run=False,
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


def conta_para_hoje(c) -> str:
    """Solicitação com admissão hoje, aprovada e criada."""
    hoje = today_in(c.app.state.settings)
    d = dados(c, data_admissao=hoje.isoformat())
    idem = re.search(
        r'name="idem" value="([0-9a-f-]{36})"',
        c.post("/solicitacoes/revisar", data=d, headers=RH).text,
    ).group(1)
    rid = (
        c.post("/solicitacoes/enviar", data={**d, "idem": idem}, headers=RH)
        .headers["location"]
        .split("/")[-1]
        .split("?")[0]
    )
    assert (
        c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI).status_code
        == 303
    )
    assert c.app.state.storage.get_request(rid).status == "conta_criada"
    return rid


def test_agendador_executa_ciclo(c):
    rid = conta_para_hoje(c)
    resp = c.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ativadas"] == [rid] and body["licenciadas"] == [rid]
    assert c.app.state.storage.get_request(rid).status == "ativa"


def test_ciclo_interno_exige_papel_de_aplicacao(c):
    for h in (RH, TI, ADM, GESTORA):
        assert c.post("/interno/ciclo-de-vida", headers=h).status_code == 403
    assert c.post("/interno/ciclo-de-vida").status_code == 401


def test_admin_executa_ciclo_pela_tela(c):
    rid = conta_para_hoje(c)
    resp = c.post("/admin/ciclo-de-vida", data={"csrf_token": csrf(c)}, headers=ADM)
    assert resp.status_code == 200 and "Ciclo de vida executado" in resp.text and rid in resp.text
    assert c.post("/admin/ciclo-de-vida", data={}, headers=ADM).status_code == 403  # CSRF


def test_gestor_ve_equipe_e_gera_tap(c):
    rid = conta_para_hoje(c)
    html = c.get("/equipe", headers=GESTORA).text
    assert "Disponível no dia da admissão" in html  # ainda não ativada
    c.post("/interno/ciclo-de-vida", headers=AGENDADOR)

    assert "começa(m) hoje" in c.get("/", headers=GESTORA).text
    html = c.get("/equipe", headers=GESTORA).text
    assert f"/equipe/{rid}/acesso-inicial" in html

    resp = c.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=GESTORA)
    assert resp.status_code == 200
    writer = c.app.state.writer
    req = c.app.state.storage.get_request(rid)
    codigo = writer.taps[req.object_id]
    assert codigo in resp.text and "uso único" in resp.text
    assert resp.headers["Cache-Control"] == "no-store"
    # nunca armazenado
    assert codigo not in req.model_dump_json()
    assert "Acesso inicial gerado" in req.historico[-1].comentario
    assert req.historico[-1].ator.nome == "Ana Gestora"
    # validade limitada pela política (480) e pela configuração
    assert writer.calls[-1].endswith(":480")


def test_somente_o_gestor_gera_tap(c):
    rid = conta_para_hoje(c)
    c.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    for h in (OUTRO, ADM, RH, TI):
        resp = c.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=h)
        assert resp.status_code == 409 and "Somente o gestor" in resp.text
    assert c.app.state.writer.taps == {}
    assert rid not in c.get("/equipe", headers=OUTRO).text


def test_tap_antes_da_ativacao_bloqueado(c):
    rid = conta_para_hoje(c)
    resp = c.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=GESTORA)
    assert resp.status_code == 409 and "ainda não foi ativada" in resp.text


def test_tap_politica_desabilitada(c):
    rid = conta_para_hoje(c)
    c.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    c.app.state.graph.tap_policy = TapPolicy(False, 60, 480, False)
    resp = c.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=GESTORA)
    assert resp.status_code == 409 and "desativado" in resp.text


def test_tap_respeita_maximo_da_politica(c):
    rid = conta_para_hoje(c)
    c.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    c.app.state.graph.tap_policy = TapPolicy(True, 60, 120, False)
    c.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=GESTORA)
    assert c.app.state.writer.calls[-1].endswith(":120")


@pytest.mark.parametrize(
    ("status", "trecho"),
    [(403, "não tem permissão"), (400, "recusou"), (503, "Tente novamente")],
)
def test_tap_erro_do_graph_mostra_motivo(c, status, trecho):
    from app.graph.errors import GraphError

    rid = conta_para_hoje(c)
    c.post("/interno/ciclo-de-vida", headers=AGENDADOR)

    def falha(user_id, minutes):
        raise GraphError(f"Graph {status} Codigo: motivo simulado", status)

    c.app.state.writer.create_temporary_access_pass = falha
    resp = c.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=GESTORA)
    assert resp.status_code == 409
    assert trecho in resp.text and "motivo simulado" not in resp.text  # detalhe só no log


def test_tap_exige_csrf(c):
    rid = conta_para_hoje(c)
    c.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    assert c.post(f"/equipe/{rid}/acesso-inicial", data={}, headers=GESTORA).status_code == 403


def test_audiencia_v1_aceita(tmp_path):
    from tests.conftest import CLIENT_ID

    s = make_settings(tmp_path, auth_mode="easyauth", website_auth_enabled=True)
    cli = TestClient(create_app(s))
    h = {H: principal_header(aud=f"api://{CLIENT_ID}")}
    assert cli.get("/api/me", headers=h).status_code == 200


def test_admissao_futura_nao_ativa(c):
    hoje = today_in(c.app.state.settings)
    d = dados(c, data_admissao=(hoje + timedelta(days=10)).isoformat())
    idem = re.search(
        r'name="idem" value="([0-9a-f-]{36})"',
        c.post("/solicitacoes/revisar", data=d, headers=RH).text,
    ).group(1)
    rid = (
        c.post("/solicitacoes/enviar", data={**d, "idem": idem}, headers=RH)
        .headers["location"]
        .split("/")[-1]
        .split("?")[0]
    )
    c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI)
    body = c.post("/interno/ciclo-de-vida", headers=AGENDADOR).json()
    assert body["ativadas"] == [] and body["licenciadas"] == []
    assert c.app.state.storage.get_request(rid).status == "conta_criada"
