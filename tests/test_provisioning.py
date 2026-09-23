"""UserProvisioningService: criação da conta, falhas parciais, idempotência e DRY_RUN."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

import pytest

from app.core.passwords import generate_password
from app.core.workflow import Pessoa, approve
from app.graph.directory import DirectoryCache
from app.graph.fake import FakeGraphService, FakeGraphWriter
from app.graph.models import Group
from app.graph.writer import DryRunWriter
from app.services.provisioning import (
    ProvisioningError,
    UserProvisioningService,
    hire_datetime,
    user_body,
)
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_settings
from tests.test_storage_contract import make_req

TI = Pessoa(oid="oid-ti", nome="TI")


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path, auth_mode="dev", dry_run=False)
    storage = SqliteStorage(str(tmp_path / "p.db"))
    graph = FakeGraphService()
    return settings, storage, DirectoryCache(graph), graph


def aprovada(storage, grupos=("g-fin", "g-vpn"), matricula="2001"):
    req = make_req(storage)
    req.dados = {
        "matricula": matricula,
        "tipo_colaborador": "funcionario",
        "cargo": "Analista",
        "departamento": "Financeiro",
        "pais": "Brasil",
        "empresa": "",
    }
    req.perfil.grupos_acesso = [{"id": g, "nome": g} for g in grupos]
    if matricula != "2001":
        upn = f"joao.{matricula}@contoso.com"
        req.conta = req.conta.model_copy(update={"user_principal_name": upn, "mail": upn})
    storage.create_request(req)
    approve(req, TI)
    return storage.update_request(req)


def service(env, writer):
    settings, storage, directory, _ = env
    return UserProvisioningService(
        settings=settings, writer=writer, directory=directory, storage=storage
    )


def test_cria_conta_desativada_com_gestor_e_grupos(env):
    _, storage, _, _ = env
    w = FakeGraphWriter()
    req = service(env, w).run(aprovada(storage))
    assert req.status == "conta_criada"
    assert req.object_id == "new-1"
    body = w.users["new-1"]
    assert body["accountEnabled"] is False
    assert body["passwordProfile"]["forceChangePasswordNextSignIn"] is True
    assert body["employeeId"] == "2001" and body["employeeType"] == "Funcionário"
    assert body["usageLocation"] == "BR"
    assert "companyName" not in body  # campos vazios não são enviados
    assert "assignedLicenses" not in body  # sem licença na criação
    assert w.managers["new-1"] == "u-1"
    assert w.members == {"g-fin": {"new-1"}, "g-vpn": {"new-1"}}
    assert all(e.status == "ok" for e in req.etapas)
    assert req.historico[-1].para == "conta_criada"
    assert req.historico[-1].ator.nome == "Portal (automático)"


def test_senha_nunca_armazenada_nem_logada(env, caplog):
    _, storage, _, _ = env
    w = FakeGraphWriter()
    caplog.set_level(logging.DEBUG)
    req = service(env, w).run(aprovada(storage))
    senha = w.users[req.object_id]["passwordProfile"]["password"]
    assert len(senha) >= 16
    assert senha not in storage.get_request(req.id).model_dump_json()
    assert senha not in caplog.text


def test_dry_run_nao_escreve_nada(env):
    settings, storage, directory, _ = env
    w = DryRunWriter()
    svc = UserProvisioningService(
        settings=settings.model_copy(update={"dry_run": True}),
        writer=w,
        directory=directory,
        storage=storage,
    )
    req = svc.run(aprovada(storage))
    assert req.status == "aprovada"  # status não muda em simulação
    assert req.object_id == ""
    assert {e.status for e in req.etapas} == {"simulado"}
    assert w.planned[0].startswith("criar ")


def test_falha_parcial_e_reprocessamento(env):
    _, storage, _, _ = env
    w = FakeGraphWriter()
    w.fail_groups = {"g-vpn"}
    svc = service(env, w)
    req = svc.run(aprovada(storage))
    assert req.status == "falha_parcial"
    status = {e.chave: e.status for e in req.etapas}
    assert status == {
        "criar_usuario": "ok",
        "definir_gestor": "ok",
        "grupo:g-fin": "ok",
        "grupo:g-vpn": "falhou",
    }
    assert "Adicionar ao grupo g-vpn" in req.historico[-1].comentario

    # Corrige a causa e reprocessa: só a etapa que falhou é executada de novo
    w.fail_groups.clear()
    w.calls.clear()
    req = svc.run(storage.get_request(req.id))
    assert req.status == "conta_criada"
    assert w.calls == ["add:g-vpn"]
    assert len(w.users) == 1  # usuário não foi recriado


def test_falha_ao_criar_deixa_demais_pendentes(env):
    _, storage, _, _ = env
    w = FakeGraphWriter()
    w.fail_create = True
    req = service(env, w).run(aprovada(storage))
    assert req.status == "falha_parcial" and req.object_id == ""
    etapas = {e.chave: e.status for e in req.etapas}
    assert etapas["criar_usuario"] == "falhou"
    assert etapas["definir_gestor"] == "pendente"
    assert w.calls == ["create_user"]


def test_reaproveita_usuario_de_tentativa_anterior(env):
    _, storage, _, _ = env
    w = FakeGraphWriter()
    req = aprovada(storage)
    w.users["antigo"] = {"userPrincipalName": req.conta.user_principal_name, "employeeId": "2001"}
    req = service(env, w).run(req)
    assert req.status == "conta_criada" and req.object_id == "antigo"
    assert "create_user" not in w.calls


def test_upn_ocupado_por_outra_pessoa(env):
    _, storage, _, _ = env
    w = FakeGraphWriter()
    req = aprovada(storage)
    w.users["outro"] = {"userPrincipalName": req.conta.user_principal_name, "employeeId": "999"}
    req = service(env, w).run(req)
    assert req.status == "falha_parcial"
    assert "ocupado" in req.etapas[0].detalhe


def test_grupo_que_virou_protegido_nao_e_usado(env):
    _, storage, _, graph = env
    graph.groups = [
        g if g.id != "g-vpn" else Group("g-vpn", "VPN", is_role_assignable=True)
        for g in graph.groups
    ]
    w = FakeGraphWriter()
    req = service(env, w).run(aprovada(storage))
    assert req.status == "falha_parcial"
    assert "g-vpn" not in w.members
    assert "não é mais permitido" in next(e for e in req.etapas if e.chave == "grupo:g-vpn").detalhe


def test_limite_diario(env):
    settings, storage, directory, _ = env
    w = FakeGraphWriter()
    svc = UserProvisioningService(
        settings=settings.model_copy(update={"provisioning_daily_limit": 1}),
        writer=w,
        directory=directory,
        storage=storage,
    )
    assert svc.run(aprovada(storage)).status == "conta_criada"
    segundo = svc.run(aprovada(storage, matricula="2002"))
    assert segundo.status == "falha_parcial" and "Limite diário" in segundo.etapas[0].detalhe


def test_nao_provisiona_fora_de_estado(env):
    _, storage, _, _ = env
    req = make_req(storage)
    storage.create_request(req)
    with pytest.raises(ProvisioningError):
        service(env, FakeGraphWriter()).run(req)


def test_data_de_admissao_em_utc(env):
    settings, storage, _, _ = env
    req = make_req(storage)
    req.data_admissao = date(2026, 10, 3)
    assert hire_datetime(req, settings) == "2026-10-03T03:00:00Z"  # 00:00 em São Paulo


def test_corpo_nao_inclui_mail_nem_licenca(env):
    settings, storage, _, _ = env
    body = user_body(make_req(storage), settings, "x" * 16)
    assert "mail" not in body and "assignedLicenses" not in body
    json.dumps(body)  # serializável


def test_gerador_de_senha():
    senhas = {generate_password() for _ in range(50)}
    assert len(senhas) == 50
    for s in senhas:
        assert len(s) == 24
        assert any(c.isupper() for c in s) and any(c.islower() for c in s)
        assert any(c.isdigit() for c in s) and any(not c.isalnum() for c in s)
    with pytest.raises(ValueError):
        generate_password(8)


def test_etapas_tem_horario(env):
    _, storage, _, _ = env
    req = service(env, FakeGraphWriter()).run(aprovada(storage))
    assert all(e.em and e.em <= datetime.now(UTC) for e in req.etapas)
