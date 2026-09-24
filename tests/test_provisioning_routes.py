"""Provisionamento disparado pela aprovação e pelo botão do Administrador."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.profiles import GroupRef, OnboardingProfile
from app.graph.fake import FakeGraphWriter
from app.main import create_app
from tests.conftest import make_settings
from tests.test_requests_routes import ADM, RH, TI, csrf, enviar


def prov(req):
    """Somente etapas do provisionamento inicial (sem as agendadas do ciclo de vida)."""
    from app.core.workflow import LIFECYCLE_KEYS

    return [e for e in req.etapas if e.chave not in LIFECYCLE_KEYS]


def build(tmp_path, dry_run: bool) -> TestClient:
    s = make_settings(
        tmp_path,
        auth_mode="easyauth",
        website_auth_enabled=True,
        m365_default_domain="contoso.com",
        dry_run=dry_run,
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


@pytest.fixture
def dry(tmp_path):
    return build(tmp_path, True)


@pytest.fixture
def real(tmp_path):
    return build(tmp_path, False)


def aprovar(c, rid):
    return c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI)


def test_aprovacao_em_dry_run_simula(dry):
    rid = enviar(dry)
    assert aprovar(dry, rid).status_code == 303
    req = dry.app.state.storage.get_request(rid)
    assert req.status == "aprovada" and req.object_id == ""
    assert {e.status for e in prov(req)} == {"simulado"}
    html = dry.get(f"/solicitacoes/{rid}?ok=aprovada", headers=TI).text
    assert "Simulada (DRY_RUN)" in html and "provisionamento foi apenas simulado" in html


def test_aprovacao_real_cria_conta(real):
    writer = real.app.state.writer
    assert isinstance(writer, FakeGraphWriter)
    rid = enviar(real)
    assert aprovar(real, rid).status_code == 303
    req = real.app.state.storage.get_request(rid)
    assert req.status == "conta_criada" and req.object_id == "new-1"
    assert writer.users["new-1"]["accountEnabled"] is False
    assert writer.members == {"g-fin": {"new-1"}}  # grupo de licença NÃO é usado agora
    html = real.get(f"/solicitacoes/{rid}", headers=RH).text
    assert "Conta criada (desativada)" in html and "new-1" in html


def test_admin_reprocessa_falha(real):
    writer = real.app.state.writer
    writer.fail_groups = {"g-fin"}
    rid = enviar(real)
    aprovar(real, rid)
    assert real.app.state.storage.get_request(rid).status == "falha_parcial"
    html = real.get(f"/solicitacoes/{rid}", headers=ADM).text
    assert "Reprocessar etapas pendentes" in html
    # RH e Aprovador não reprocessam
    assert (
        real.post(
            f"/solicitacoes/{rid}/provisionar", data={"csrf_token": csrf(real)}, headers=TI
        ).status_code
        == 403
    )
    writer.fail_groups.clear()
    resp = real.post(
        f"/solicitacoes/{rid}/provisionar", data={"csrf_token": csrf(real)}, headers=ADM
    )
    assert resp.status_code == 303
    assert real.app.state.storage.get_request(rid).status == "conta_criada"
    assert len(writer.users) == 1


def test_admin_executa_real_apos_simulacao(tmp_path):
    """Aprovada em DRY_RUN; depois DRY_RUN=false e o Administrador cria a conta."""
    c = build(tmp_path, True)
    rid = enviar(c)
    aprovar(c, rid)
    c.app.state.settings = c.app.state.settings.model_copy(update={"dry_run": False})
    c.app.state.writer = FakeGraphWriter()
    resp = c.post(f"/solicitacoes/{rid}/provisionar", data={"csrf_token": csrf(c)}, headers=ADM)
    assert resp.status_code == 303
    req = c.app.state.storage.get_request(rid)
    assert req.status == "conta_criada" and {e.status for e in prov(req)} == {"ok"}


def test_nao_provisiona_pendente_nem_criada(real):
    rid = enviar(real)
    resp = real.post(
        f"/solicitacoes/{rid}/provisionar", data={"csrf_token": csrf(real)}, headers=ADM
    )
    assert resp.status_code == 409
    aprovar(real, rid)
    resp = real.post(
        f"/solicitacoes/{rid}/provisionar", data={"csrf_token": csrf(real)}, headers=ADM
    )
    assert resp.status_code == 409  # já está conta_criada
    assert len(real.app.state.writer.users) == 1


def test_provisionar_exige_csrf(real):
    rid = enviar(real)
    assert real.post(f"/solicitacoes/{rid}/provisionar", data={}, headers=ADM).status_code == 403
