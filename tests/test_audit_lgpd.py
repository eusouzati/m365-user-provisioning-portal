"""Sprint 9: auditoria automática, painel, LGPD e ajustes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles
from app.core.audit import AuditEvent
from app.core.profiles import GroupRef, OnboardingProfile
from app.core.workflow import ANON, Pessoa, approve, reject
from app.main import create_app
from app.services.privacy import anonymize, eligible, run_retention
from app.storage.auditing import AuditingStorage
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_settings, principal_header
from tests.test_requests_routes import ADM, RH, TI, csrf, enviar
from tests.test_storage_contract import make_req

H = "X-MS-CLIENT-PRINCIPAL"
GESTORA = {H: principal_header(oid="u-1", name="Ana Gestora")}
SEM_PAPEL = {H: principal_header(oid="zzz", name="Zé")}


def _app(tmp_path, **over):
    s = make_settings(
        tmp_path,
        auth_mode="easyauth",
        website_auth_enabled=True,
        m365_default_domain="contoso.com",
        dry_run=False,
        **over,
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
def c(tmp_path) -> TestClient:
    return _app(tmp_path)


def eventos(c, **kw):
    return list(reversed(c.app.state.storage.list_audit(**kw)))


# --------------------------------------------------------------- auditoria
def test_fluxo_completo_gera_auditoria_com_ator_certo(c):
    rid = enviar(c)
    c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI)
    ev = [(e.acao, e.ator_nome) for e in eventos(c) if e.alvo == rid]
    assert ("solicitacao.enviada", "Rita RH") in ev
    assert ("solicitacao.aprovada", "Tina TI") in ev
    assert ("conta.criada", "Portal (automático)") in ev
    assert ("etapa.ok", "Tina TI") in ev  # quem disparou a criação
    assert all(e.tipo == "admissao" for e in eventos(c) if e.alvo == rid)


def test_auditoria_sem_dados_pessoais_do_colaborador(c):
    rid = enviar(c)
    dados = {"csrf_token": csrf(c), "comentario": "CPF 123 errado"}
    c.post(f"/aprovacoes/{rid}/rejeitar", data=dados, headers=TI)
    textos = " ".join(f"{e.detalhe} {e.alvo}" for e in eventos(c))
    assert "joao.silva" not in textos and "João" not in textos
    assert "CPF 123" not in textos  # comentário humano fica só na solicitação


def test_perfil_auditado_com_ator(c):
    c.post("/admin/perfis/p-fin/excluir", data={"csrf_token": csrf(c)}, headers=ADM)
    ultimo = c.app.state.storage.list_audit(limit=1)[0]
    assert (ultimo.acao, ultimo.alvo) == ("perfil.excluido", "perfil:p-fin")
    assert ultimo.ator_nome == "Adm"


def test_tap_auditado_sem_o_codigo(tmp_path):
    from tests.test_team_routes import AGENDADOR, conta_para_hoje

    cli = _app(tmp_path)
    rid = conta_para_hoje(cli)
    cli.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    cli.post(f"/equipe/{rid}/acesso-inicial", data={"csrf_token": csrf(cli)}, headers=GESTORA)
    codigo = next(iter(cli.app.state.writer.taps.values()))
    tap = [e for e in eventos(cli) if e.acao == "acesso_inicial.gerado"]
    assert tap and tap[0].ator_nome == "Ana Gestora"
    assert codigo not in " ".join(e.model_dump_json() for e in eventos(cli))
    ativ = [e for e in eventos(cli) if e.acao == "conta.ativada"]
    assert ativ and any(
        e.acao == "ciclo.executado" and "Agendador" in e.ator_nome for e in eventos(cli)
    )


def test_falha_na_auditoria_nao_derruba_a_operacao(tmp_path, caplog):
    inner = SqliteStorage(str(tmp_path / "a.db"))
    storage = AuditingStorage(inner)

    def quebra(ev):
        raise RuntimeError("tabela indisponível")

    inner.append_audit = quebra
    req = make_req(storage)
    storage.create_request(req)
    approve(req, Pessoa(oid="ti", nome="TI"))
    storage.update_request(req)  # gera evento; a falha é só registrada no log
    assert storage.get_request(req.id).status == "aprovada"
    assert "Falha ao gravar evento de auditoria" in caplog.text


def test_tela_de_auditoria_e_filtros(c):
    rid = enviar(c)
    assert c.get("/admin/auditoria", headers=RH).status_code == 403
    html = c.get("/admin/auditoria", headers=ADM).text
    assert rid in html and "Solicitação enviada" in html
    html = c.get("/admin/auditoria?acao=perfil.criado", headers=ADM).text
    assert rid not in html and "perfil:p-fin" in html
    html = c.get(f"/admin/auditoria?alvo={rid}&ator=rita", headers=ADM).text
    assert rid in html
    assert "Nenhum evento" in c.get("/admin/auditoria?ator=ninguem", headers=ADM).text


def test_exportacao_csv(c):
    storage = c.app.state.storage
    storage.append_audit(
        AuditEvent(
            ator_oid="x", ator_nome="=HYPERLINK(1)", acao="solicitacao.registro", detalhe="@SOMA(1)"
        )
    )
    resp = c.get("/admin/auditoria.csv", headers=ADM)
    assert resp.status_code == 200 and resp.text.startswith("﻿data_hora;acao;")
    assert "attachment;" in resp.headers["Content-Disposition"]
    assert "'=HYPERLINK(1)" in resp.text and "'@SOMA(1)" in resp.text  # sem fórmulas
    assert storage.list_audit(limit=1)[0].acao == "auditoria.exportada"
    assert c.get("/admin/auditoria.csv", headers=TI).status_code == 403


# ------------------------------------------------------------------- painel
def test_painel(c):
    rid = enviar(c)
    c.post("/admin/ciclo-de-vida", data={"csrf_token": csrf(c)}, headers=ADM)
    html = c.get("/admin/painel", headers=ADM).text
    assert "Aguardando aprovação" in html and "Última execução" in html
    assert "Microsoft 365 E3" in html and rid in html
    assert c.get("/admin/painel", headers=TI).status_code == 403
    assert c.app.state.storage.get_state("ultimo_ciclo")["analisadas"] == 0


# --------------------------------------------------------------------- LGPD
def _finalizada(storage, dias_atras: int, status="rejeitada"):
    req = make_req(storage)
    storage.create_request(req)
    if status == "rejeitada":
        reject(req, Pessoa(oid="ti", nome="TI"), "motivo com dado pessoal: CPF 999")
    else:
        approve(req, Pessoa(oid="ti", nome="TI"))
        req.status = status
    req.object_id = "oid-conta"
    req = storage.update_request(req)
    req.atualizado_em = datetime.now(UTC) - timedelta(days=dias_atras)
    return storage.update_request(req)


def test_elegiveis_respeitam_prazo_e_status(tmp_path):
    s = make_settings(tmp_path, lgpd_retention_days=30)
    storage = AuditingStorage(SqliteStorage(str(tmp_path / "l.db")))
    velha = _finalizada(storage, 40)
    _finalizada(storage, 10)  # dentro do prazo
    andamento = make_req(storage)
    storage.create_request(andamento)  # não final
    assert [r.id for r in eligible(storage.list_requests(), s)] == [velha.id]
    assert eligible(storage.list_requests(), s.model_copy(update={"lgpd_retention_days": 0})) == []


def test_anonimizacao_remove_dados_pessoais(tmp_path):
    s = make_settings(tmp_path, lgpd_retention_days=30)
    storage = AuditingStorage(SqliteStorage(str(tmp_path / "l.db")))
    velha = _finalizada(storage, 40)
    assert run_retention(storage, s) == [velha.id]
    r = storage.get_request(velha.id)
    dump = r.model_dump_json()
    for dado in ("joao.silva", "João", "CPF 999", "Ana"):
        assert dado not in dump
    assert r.conta.display_name == ANON and r.anonimizado_em is not None
    assert r.object_id == "oid-conta" and r.solicitante.nome == "RH"  # responsabilização
    assert storage.list_audit(limit=1)[0].acao == "lgpd.anonimizado"
    assert run_retention(storage, s) == []  # idempotente


def test_agendador_executa_retencao_e_nao_toca_no_m365(tmp_path):
    cli = _app(tmp_path, lgpd_retention_days=30)
    velha = _finalizada(cli.app.state.storage, 40)
    from tests.test_team_routes import AGENDADOR

    body = cli.post("/interno/ciclo-de-vida", headers=AGENDADOR).json()
    assert body["anonimizadas"] == [velha.id]
    assert cli.app.state.writer.calls == []


def test_tela_de_privacidade_e_botao(tmp_path):
    cli = _app(tmp_path, lgpd_retention_days=30, privacy_contact="dpo@contoso.com")
    velha = _finalizada(cli.app.state.storage, 40)
    html = cli.get("/admin/privacidade", headers=ADM).text
    assert "Prontas para anonimizar (1)" in html and velha.id in html
    assert cli.post("/admin/privacidade/anonimizar", data={}, headers=ADM).status_code == 403
    resp = cli.post("/admin/privacidade/anonimizar", data={"csrf_token": csrf(cli)}, headers=ADM)
    assert resp.status_code == 303 and resp.headers["location"].endswith("ok=1")
    assert cli.app.state.storage.get_request(velha.id).anonimizado_em is not None
    assert cli.get("/admin/privacidade", headers=TI).status_code == 403


def test_aviso_de_privacidade_para_qualquer_usuario(tmp_path):
    cli = _app(tmp_path, privacy_contact="dpo@contoso.com", lgpd_retention_days=730)
    html = cli.get("/privacidade", headers=SEM_PAPEL).text
    assert "Aviso de privacidade" in html and "dpo@contoso.com" in html and "730 dias" in html
    assert cli.get("/privacidade").status_code in (302, 401)


def test_anonimizar_mantem_estrutura_valida(tmp_path):
    storage = SqliteStorage(str(tmp_path / "x.db"))
    req = make_req(storage)
    anonymize(req, 30)
    from app.core.workflow import ProvisioningRequest

    ProvisioningRequest.model_validate_json(req.model_dump_json())


# ------------------------------------------------------------------ ajustes
def test_aviso_comeca_hoje_so_para_admissao_do_dia(tmp_path):
    from tests.test_team_routes import AGENDADOR, conta_para_hoje

    cli = _app(tmp_path)
    rid = conta_para_hoje(cli)
    cli.post("/interno/ciclo-de-vida", headers=AGENDADOR)
    assert "começa(m) hoje" in cli.get("/", headers=GESTORA).text
    storage = cli.app.state.storage
    req = storage.get_request(rid)
    req.data_admissao = req.data_admissao - timedelta(days=1)  # admitido ontem
    storage.update_request(req)
    assert "começa(m) hoje" not in cli.get("/", headers=GESTORA).text


def test_admissao_mostra_desligado_depois(tmp_path):
    cli = _app(tmp_path)
    storage = cli.app.state.storage
    adm = make_req(storage)
    adm.object_id, adm.status = "u-3", "ativa"
    storage.create_request(adm)
    from tests.test_offboarding import aprovar, pedir

    assert "Desligado depois" not in cli.get("/admin/solicitacoes", headers=ADM).text
    rid = pedir(cli, imediato="on")
    aprovar(cli, rid)
    assert "Desligado depois" in cli.get("/admin/solicitacoes", headers=ADM).text


def test_logs_ruidosos_silenciados(tmp_path):
    _app(tmp_path)
    for nome in ("azure.core.pipeline.policies.http_logging_policy", "httpx", "azure.identity"):
        assert logging.getLogger(nome).getEffectiveLevel() >= logging.WARNING


def test_menu_admin_aponta_para_o_painel(c):
    html = c.get("/", headers=ADM).text
    assert 'href="/admin/painel"' in html and 'href="/privacidade"' in html
    assert Roles.ADMINISTRADOR


# ------------------------------------------------- revisão independente
def test_filtro_de_periodo_usa_o_fuso_local(c):
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    storage = c.app.state.storage
    for hora, dia, nome in ((22, 23, "antes"), (23, 24, "dentro")):
        storage.append_audit(
            AuditEvent(
                em=datetime(2026, 9, dia, hora, 30, tzinfo=tz),
                ator_oid="x",
                ator_nome=nome,
                acao="solicitacao.registro",
            )
        )
    html = c.get("/admin/auditoria?de=2026-09-24&ate=2026-09-24", headers=ADM).text
    assert "dentro" in html and "antes" not in html


def test_auditoria_sem_nome_do_gestor_nem_upn(c):
    rid = enviar(c)
    c.app.state.writer.fail_groups.add("g-fin")
    c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=TI)
    textos = " ".join(e.detalhe for e in eventos(c))
    assert "Ana Gestora" not in textos and "@contoso.com" not in textos
    assert "Definir gestor" in textos


def test_redact():
    from app.core.audit import redact

    t = redact("Falha em: Definir gestor: Maria Silva; O UPN joao@x.com foi ocupado")
    assert t == "Falha em: Definir gestor; O UPN [e-mail] foi ocupado"
    assert redact("Falha em: Definir gestor: Maria S. Souza; Grupo X") == (
        "Falha em: Definir gestor; Grupo X"
    )
    assert redact("Definir gestor: José Jr.") == "Definir gestor"


def test_anonimizacao_limpa_comentarios_do_sistema(tmp_path):
    from app.core.workflow import SISTEMA, note

    s = make_settings(tmp_path, lgpd_retention_days=30)
    storage = AuditingStorage(SqliteStorage(str(tmp_path / "l.db")))
    velha = _finalizada(storage, 40)
    note(velha, SISTEMA, "Falha em: Definir gestor: Maria Gestora; UPN joao@x.com")
    velha = storage.update_request(velha)
    velha.atualizado_em = datetime.now(UTC) - timedelta(days=40)
    storage.update_request(velha)
    run_retention(storage, s, ator=Pessoa(oid="adm", nome="Adm"))
    dump = storage.get_request(velha.id).model_dump_json()
    assert "Maria Gestora" not in dump and "joao@x.com" not in dump
    ev = [e for e in storage.list_audit() if e.acao == "lgpd.anonimizado"][0]
    assert ev.ator_nome == "Adm"


def test_falha_na_retencao_nao_impede_o_ciclo(tmp_path, monkeypatch):
    import app.services.lifecycle as lc
    from tests.test_team_routes import AGENDADOR, conta_para_hoje

    cli = _app(tmp_path, lgpd_retention_days=30)
    rid = conta_para_hoje(cli)

    def quebra(*a, **k):
        raise RuntimeError("tabela fora do ar")

    monkeypatch.setattr(lc, "run_retention", quebra)
    body = cli.post("/interno/ciclo-de-vida", headers=AGENDADOR).json()
    assert body["ativadas"] == [rid]


def test_exportacao_e_painel_sobrevivem_a_falha_da_auditoria(c, monkeypatch):
    inner = c.app.state.storage._inner

    def quebra(*a, **k):
        raise RuntimeError("auditoria indisponível")

    monkeypatch.setattr(inner, "append_audit", quebra)
    assert c.get("/admin/auditoria.csv", headers=ADM).status_code == 200
    monkeypatch.setattr(inner, "list_audit", quebra)
    assert c.get("/admin/painel", headers=ADM).status_code == 200


def test_exportacao_nao_grava_o_texto_do_filtro(c):
    c.get("/admin/auditoria.csv?ator=joao.silva", headers=ADM)
    ev = c.app.state.storage.list_audit(limit=1)[0]
    assert ev.acao == "auditoria.exportada"
    assert "joao" not in ev.detalhe and "filtro ator" in ev.detalhe
