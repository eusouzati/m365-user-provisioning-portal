"""Desligamento: motor (etapas, ações manuais, falhas) e fluxo HTTP completo."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles
from app.core.workflow import Pessoa, approve
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError
from app.graph.fake import SKU_E3, FakeGraphService, FakeGraphWriter
from app.graph.models import LicenseState
from app.graph.writer import DryRunWriter
from app.main import create_app
from app.services.lifecycle import LifecycleService
from app.services.offboarding import (
    OffboardingService,
    block_at,
    new_offboarding_request,
    run_offboarding_if_due,
)
from app.services.onboarding import today_in
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_settings, principal_header
from tests.test_requests_routes import ADM, RH, TI, csrf
from tests.test_storage_contract import make_req

H = "X-MS-CLIENT-PRINCIPAL"
JOAO = "u-3"  # João Silva no Graph simulado (gestora: Ana, u-1)
ULTIMO_DIA = date(2026, 10, 9)


# ------------------------------------------------------------------ motor
@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path, auth_mode="dev", dry_run=False)
    storage = SqliteStorage(str(tmp_path / "o.db"))
    graph = FakeGraphService()
    return settings, storage, DirectoryCache(graph), graph, FakeGraphWriter()


def agendado(env, *, imediato=False, dia=ULTIMO_DIA):
    settings, storage, directory, graph, writer = env
    from app.core.offboarding import OffboardingForm
    from app.services.offboarding import OffboardingReview

    user = graph.get_user(JOAO)
    form = OffboardingForm(colaborador_id=JOAO, data_desligamento=dia, imediato=imediato)
    review = OffboardingReview(form=form, user=user, gestor=graph.get_manager(JOAO))

    class P:
        object_id, name, username = "oid-rh", "Rita RH", "rita"

    req = new_offboarding_request(
        review, settings=settings, storage=storage, principal=P(), idempotency_key=f"k-{dia}"
    )
    storage.create_request(req)
    approve(req, Pessoa(oid="oid-ti", nome="TI"))
    req = storage.update_request(req)
    return run_offboarding_if_due(
        req, settings=settings, writer=writer, directory=directory, storage=storage
    )


def motor(env, **over):
    settings, storage, directory, _, writer = env
    return LifecycleService(
        settings=settings.model_copy(update=over),
        writer=writer,
        directory=directory,
        storage=storage,
    )


def etapa(req, chave):
    return next(e for e in req.etapas if e.chave == chave)


def bloqueio(env):
    """18:00 de 09/10/2026 em São Paulo = 21:00 UTC."""
    return datetime(2026, 10, 9, 21, 0, tzinfo=UTC)


def test_agendamento_mostra_etapas_e_horario(env):
    req = agendado(env)
    assert req.status == "aprovada" and req.status_label == "Desligamento agendado"
    assert block_at(req, env[0]) == bloqueio(env)
    assert [e.chave for e in req.etapas] == ["bloquear", "revogar_sessoes", "data_saida", "grupos"]
    assert "09/10/2026 às 18:00" in etapa(req, "bloquear").detalhe


def test_antes_do_horario_nada_acontece(env):
    _, storage, _, _, writer = env
    req = agendado(env)
    rel = motor(env).run(now=bloqueio(env) - timedelta(minutes=1))
    assert rel.desligadas == [] and writer.calls == []
    assert storage.get_request(req.id).status == "aprovada"


def test_no_horario_bloqueia_revoga_e_remove_grupos(env):
    _, storage, _, _, writer = env
    req = agendado(env)
    rel = motor(env).run(now=bloqueio(env))
    req = storage.get_request(req.id)
    assert rel.desligadas == [req.id]
    assert req.status == "desligada"
    assert writer.calls[0] == f"disable:{JOAO}"  # o bloqueio vem primeiro
    assert JOAO in writer.disabled and JOAO in writer.revoked
    assert writer.leave_dates[JOAO] == "2026-10-09T21:00:00Z"
    # grupos removíveis: segurança, M365 e licença
    assert set(writer.removed) == {"g-fin", "g-vpn", "g-lic-e3", "g-all"}
    # dinâmico e com funções: ação manual, sem chamada ao Graph
    assert etapa(req, "manual:grupo:g-dyn").status == "manual"
    assert etapa(req, "manual:grupo:g-admins").status == "manual"
    assert "remove:g-dyn" not in writer.calls and "remove:g-admins" not in writer.calls
    assert "(licença)" in etapa(req, "rgrupo:g-lic-e3").nome
    assert "não foi excluída" in req.historico[-1].comentario


def test_nunca_exclui_o_usuario(env):
    _, _, _, _, writer = env
    agendado(env, imediato=True)
    assert not any("delete" in c.lower() for c in writer.calls)
    assert not hasattr(writer, "delete_user")


def test_imediato_executa_na_aprovacao(env):
    req = agendado(env, imediato=True)
    assert req.status == "desligada"
    assert [e.para for e in req.historico][-2:] == ["aprovada", "desligada"]


def test_data_passada_executa_na_aprovacao(env):
    req = agendado(env, dia=date(2020, 1, 1))
    assert req.status == "desligada"


def test_subordinados_funcoes_e_licenca_direta_viram_acao_manual(env):
    _, storage, _, graph, writer = env
    graph.managers["u-2"] = JOAO  # Bruno reporta ao João
    graph.directory_roles[JOAO] = 1
    graph.license_states[JOAO] = [LicenseState(SKU_E3, False)]
    req = agendado(env, imediato=True)
    assert "Bruno Lima" in etapa(req, "manual:subordinados").detalhe
    assert etapa(req, "manual:funcoes").status == "manual"
    lic = etapa(req, f"manual:licenca:{SKU_E3}")
    assert lic.status == "manual" and "SPE_E3" in lic.nome
    assert writer.removed_licenses == {}
    assert req.status == "desligada"  # ações manuais não impedem a conclusão


def test_licenca_direta_removida_no_modo_direct(env):
    settings, storage, directory, graph, writer = env
    graph.license_states[JOAO] = [LicenseState(SKU_E3, False)]
    direct = settings.model_copy(update={"license_mode": "direct"})
    env2 = (direct, storage, directory, graph, writer)
    req = agendado(env2, imediato=True)
    assert etapa(req, f"rlicenca:{SKU_E3}").status == "ok"
    assert writer.removed_licenses[JOAO] == {SKU_E3}


def test_falha_no_bloqueio_continua_e_tenta_de_novo(env):
    _, storage, _, _, writer = env
    writer.fail_disable = True
    req = agendado(env, imediato=True)
    assert req.status == "falha_parcial"
    assert etapa(req, "bloquear").status == "falhou"
    assert "permissão" in etapa(req, "bloquear").detalhe
    assert JOAO in writer.revoked and "g-fin" in writer.removed  # o resto foi feito

    writer.fail_disable = False
    writer.calls.clear()
    rel = motor(env).run(now=bloqueio(env))
    req = storage.get_request(req.id)
    assert rel.desligadas == [req.id] and req.status == "desligada"
    assert writer.calls == [f"disable:{JOAO}"]  # só a etapa que faltava


def test_falha_ao_listar_grupos_nao_impede_o_bloqueio(env, monkeypatch):
    _, storage, _, graph, writer = env

    def falha(uid):
        raise GraphError("Graph 503 ServiceUnavailable: tente depois", 503)

    monkeypatch.setattr(graph, "list_memberships", falha)
    req = agendado(env, imediato=True)
    assert JOAO in writer.disabled
    assert req.status == "falha_parcial" and etapa(req, "grupos").status == "falhou"

    monkeypatch.undo()
    motor(env).run(now=bloqueio(env))
    req = storage.get_request(req.id)
    assert req.status == "desligada" and "g-fin" in writer.removed


def test_desligado_nao_e_reprocessado(env):
    _, _, _, _, writer = env
    agendado(env, imediato=True)
    writer.calls.clear()
    rel = motor(env).run(now=bloqueio(env) + timedelta(days=3))
    assert rel.analisadas == 0 and writer.calls == []


def test_dry_run_so_simula(env):
    settings, storage, directory, _, _ = env
    dry = DryRunWriter()
    req = agendado((settings, storage, directory, env[3], dry), imediato=True)
    assert req.status == "aprovada"
    assert all(e.status in ("simulado", "manual") for e in req.etapas)
    rel = LifecycleService(settings=settings, writer=dry, directory=directory, storage=storage).run(
        now=bloqueio(env)
    )
    assert rel.dry_run and rel.desligadas == []


def test_admissao_nao_trata_desligamento(env):
    """O motor de admissão ignora desligamentos (mesmo em falha parcial)."""
    _, storage, _, _, writer = env
    writer.fail_disable = True
    req = agendado(env, imediato=True)
    writer.fail_disable = False
    writer.calls.clear()
    motor(env).run(now=bloqueio(env))
    assert not any(c.startswith(("enable:", "license:")) for c in writer.calls)
    assert storage.get_request(req.id).status == "desligada"


# ------------------------------------------------------------------- HTTP
JOAO_H = {H: principal_header(oid=JOAO, name="João Silva", roles=(Roles.SOLICITANTE,))}
JOAO_TI = {H: principal_header(oid=JOAO, name="João Silva", roles=(Roles.APROVADOR,))}
GESTORA = {H: principal_header(oid="u-1", name="Ana Gestora")}


@pytest.fixture
def c(tmp_path) -> TestClient:
    s = make_settings(
        tmp_path,
        auth_mode="easyauth",
        website_auth_enabled=True,
        m365_default_domain="contoso.com",
        dry_run=False,
    )
    return TestClient(create_app(s), follow_redirects=False)


def form(c, headers=RH, **kw):
    d = {
        "csrf_token": csrf(c, headers),
        "colaborador_id": JOAO,
        "colaborador_nome": "João Silva",
        "data_desligamento": (today_in(c.app.state.settings) + timedelta(days=7)).isoformat(),
    }
    d.update(kw)
    return d


def pedir(c, headers=RH, **kw) -> str:
    d = form(c, headers, **kw)
    resp = c.post("/desligamentos/revisar", data=d, headers=headers)
    assert resp.status_code == 200, resp.text
    idem = re.search(r'name="idem" value="([0-9a-f-]{36})"', resp.text).group(1)
    resp = c.post("/desligamentos/enviar", data={**d, "idem": idem}, headers=headers)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"].split("/")[-1].split("?")[0]


def aprovar(c, rid, headers=TI):
    return c.post(f"/aprovacoes/{rid}/aprovar", data={"csrf_token": csrf(c)}, headers=headers)


def test_formulario_e_revisao(c):
    assert c.get("/desligamentos/novo", headers=RH).status_code == 200
    assert c.get("/desligamentos/novo", headers=TI).status_code == 403
    html = c.post("/desligamentos/revisar", data=form(c), headers=RH).text
    assert "Revisar desligamento" in html and "joao.silva@contoso.com" in html
    assert "Financeiro" in html and "Todos (dinâmico)" in html and "não é excluída" in html


def test_formulario_exige_colaborador(c):
    resp = c.post("/desligamentos/revisar", data=form(c, colaborador_id=""), headers=RH)
    assert resp.status_code == 422 and "Selecione o colaborador" in resp.text
    resp = c.post("/desligamentos/revisar", data=form(c, colaborador_id="u-999"), headers=RH)
    assert resp.status_code == 422 and "não encontrado" in resp.text


def test_formulario_exige_csrf(c):
    d = form(c)
    d.pop("csrf_token")
    assert c.post("/desligamentos/revisar", data=d, headers=RH).status_code == 403


def test_fluxo_agendado(c):
    rid = pedir(c)
    req = c.app.state.storage.get_request(rid)
    assert req.tipo == "desligamento" and req.status == "enviada" and req.object_id == JOAO
    assert "Desligamento" in c.get("/solicitacoes", headers=RH).text

    assert aprovar(c, rid).status_code == 303
    req = c.app.state.storage.get_request(rid)
    assert req.status == "aprovada" and etapa(req, "bloquear").detalhe.startswith("Agendada")
    assert c.app.state.writer.disabled == set()
    html = c.get(f"/solicitacoes/{rid}", headers=RH).text
    assert "Desligamento agendado" in html and "Cancelar desligamento agendado" in html


def test_fluxo_imediato(c):
    rid = pedir(c, imediato="on")
    aprovar(c, rid)
    req = c.app.state.storage.get_request(rid)
    assert req.status == "desligada"
    assert JOAO in c.app.state.writer.disabled
    html = c.get(f"/solicitacoes/{rid}", headers=ADM).text
    assert "Ação manual" in html and "Restam ações manuais" in html


def test_ninguem_pede_o_proprio_desligamento(c):
    resp = c.post("/desligamentos/revisar", data=form(c, JOAO_H), headers=JOAO_H)
    assert resp.status_code == 422 and "próprio desligamento" in resp.text


def test_quem_pediu_nao_aprova(c):
    from tests.test_requests_routes import RH_E_TI

    rid = pedir(c, RH_E_TI)
    assert aprovar(c, rid, RH_E_TI).status_code == 409
    assert c.app.state.storage.get_request(rid).status == "enviada"


def test_um_desligamento_por_vez(c):
    rid = pedir(c)
    resp = c.post("/desligamentos/revisar", data=form(c), headers=RH)
    assert resp.status_code == 422 and rid in resp.text


def test_cancelar_agendado_e_nao_depois_de_executado(c):
    rid = pedir(c)
    aprovar(c, rid)
    resp = c.post(f"/solicitacoes/{rid}/cancelar", data={"csrf_token": csrf(c)}, headers=RH)
    assert resp.status_code == 303
    assert c.app.state.storage.get_request(rid).status == "cancelada"

    rid2 = pedir(c, imediato="on")
    aprovar(c, rid2)
    resp = c.post(f"/solicitacoes/{rid2}/cancelar", data={"csrf_token": csrf(c)}, headers=ADM)
    assert resp.status_code == 409
    assert c.app.state.storage.get_request(rid2).status == "desligada"


def test_admin_executa_agora(c):
    rid = pedir(c)
    aprovar(c, rid)
    html = c.get(f"/solicitacoes/{rid}", headers=ADM).text
    assert "Executar desligamento agora" in html and "antes do horário agendado" in html
    resp = c.post(f"/solicitacoes/{rid}/provisionar", data={"csrf_token": csrf(c)}, headers=ADM)
    assert resp.status_code == 303
    assert c.app.state.storage.get_request(rid).status == "desligada"


def test_agendador_executa_no_horario(c):
    agendador = {H: principal_header(oid="mi", name="", roles=(Roles.AGENDADOR,))}
    rid = pedir(c)
    aprovar(c, rid)
    assert c.post("/interno/ciclo-de-vida", headers=agendador).json()["desligadas"] == []
    # o tempo passa: o último dia chegou e o horário do bloqueio já passou
    storage = c.app.state.storage
    req = storage.get_request(rid)
    req.data_desligamento = today_in(c.app.state.settings) - timedelta(days=1)
    storage.update_request(req)
    body = c.post("/interno/ciclo-de-vida", headers=agendador).json()
    assert body["desligadas"] == [rid]
    assert storage.get_request(rid).status == "desligada"


def test_desligamento_nao_aparece_em_minha_equipe(c):
    rid = pedir(c, imediato="on")
    aprovar(c, rid)
    assert rid not in c.get("/equipe", headers=GESTORA).text


# ------------------------------------------------- revisão independente
JOAO_ADM = {
    H: principal_header(oid=JOAO, name="João Silva", roles=(Roles.APROVADOR, Roles.ADMINISTRADOR))
}


def test_o_proprio_colaborador_nao_ve_nem_decide(c):
    rid = pedir(c)
    tok = csrf(c)
    assert c.get(f"/solicitacoes/{rid}", headers=JOAO_ADM).status_code == 404
    assert rid not in c.get("/aprovacoes", headers=JOAO_ADM).text
    assert rid not in c.get("/admin/solicitacoes", headers=JOAO_ADM).text
    for acao in ("aprovar", "rejeitar"):
        c.post(
            f"/aprovacoes/{rid}/{acao}",
            data={"csrf_token": tok, "comentario": "não quero"},
            headers=JOAO_ADM,
        )
    assert c.app.state.storage.get_request(rid).status == "enviada"
    aprovar(c, rid)
    c.post(f"/solicitacoes/{rid}/cancelar", data={"csrf_token": tok}, headers=JOAO_ADM)
    assert c.app.state.storage.get_request(rid).status == "aprovada"


def test_regra_do_alvo_tambem_no_workflow(env):
    from app.core.workflow import WorkflowError, cancel, reject

    req = agendado(env)
    alvo = Pessoa(oid=JOAO, nome="João")
    with pytest.raises(WorkflowError, match="próprio desligamento"):
        cancel(req, alvo, is_admin=True)
    req.status = "enviada"
    with pytest.raises(WorkflowError, match="próprio desligamento"):
        reject(req, alvo, "motivo qualquer")
    with pytest.raises(WorkflowError, match="próprio desligamento"):
        approve(req, alvo)


def test_admissao_em_andamento_e_encerrada_na_aprovacao(c):
    storage = c.app.state.storage
    adm = make_req(storage)
    adm.object_id, adm.status = JOAO, "conta_criada"  # contratado que não compareceu
    storage.create_request(adm)
    html = c.post("/desligamentos/revisar", data=form(c), headers=RH).text
    assert "será encerrada na aprovação" in html and adm.id in html
    rid = pedir(c)
    aprovar(c, rid)
    adm = storage.get_request(adm.id)
    assert adm.status == "cancelada" and rid in adm.historico[-1].comentario


def test_agendador_nunca_ativa_conta_em_desligamento(env):
    settings, storage, directory, _, writer = env
    from app.core.workflow import Etapa

    adm = make_req(storage, idem="adm-1")
    adm.object_id, adm.status = JOAO, "conta_criada"
    adm.data_admissao, adm.data_licenca = date(2026, 1, 1), None
    adm.etapas = [Etapa(chave="criar_usuario", nome="Criar", status="ok")]
    storage.create_request(adm)
    agendado(env)  # desligamento aprovado (agendado) para a mesma conta
    motor(env).run(today=date(2026, 9, 30), now=bloqueio(env) - timedelta(days=1))
    assert f"enable:{JOAO}" not in writer.calls
    assert storage.get_request(adm.id).status == "conta_criada"


def test_simulacao_nao_congela_a_lista_de_grupos(env):
    settings, storage, directory, graph, writer = env
    dry = DryRunWriter()
    req = agendado((settings, storage, directory, graph, dry), imediato=True)
    assert req.status == "aprovada"
    graph.memberships[JOAO].append("g-rh")  # entrou num grupo depois da simulação
    OffboardingService(settings=settings, writer=writer, directory=directory, storage=storage).run(
        storage.get_request(req.id)
    )
    assert "g-rh" in writer.removed
    assert storage.get_request(req.id).status == "desligada"


def test_simulacao_nao_apaga_execucao_real(env):
    settings, storage, directory, graph, writer = env
    writer.fail_disable = True
    req = agendado(env, imediato=True)
    antes = [(e.chave, e.status) for e in req.etapas]
    OffboardingService(
        settings=settings, writer=DryRunWriter(), directory=directory, storage=storage
    ).run(storage.get_request(req.id))
    assert [(e.chave, e.status) for e in storage.get_request(req.id).etapas] == antes


def test_execucao_reserva_a_solicitacao_antes_de_escrever(env):
    from app.core.workflow import can_cancel, cancel
    from app.storage.errors import ConcurrencyError

    settings, storage, directory, _, writer = env
    req = agendado(env)
    copia_antiga = storage.get_request(req.id)
    vistos = []

    def ao_bloquear(uid):
        vistos.append(storage.get_request(req.id).execucao_em)  # já reservado no Graph-time
        writer.disabled.add(uid)

    writer.disable_user = ao_bloquear
    OffboardingService(settings=settings, writer=writer, directory=directory, storage=storage).run(
        storage.get_request(req.id)
    )
    assert vistos and vistos[0] is not None
    atual = storage.get_request(req.id)
    assert atual.status == "desligada" and not can_cancel(atual)
    cancel(copia_antiga, Pessoa(oid="oid-rh", nome="RH"))
    with pytest.raises(ConcurrencyError):
        storage.update_request(copia_antiga)


def test_data_de_saida_imediata_nao_muda_nas_novas_tentativas(env):
    settings, storage, directory, _, writer = env
    writer.fail_disable = True
    req = agendado(env, imediato=True)
    primeira = writer.leave_dates[JOAO]
    writer.fail_disable = False
    req = storage.get_request(req.id)
    etapa(req, "data_saida").status = "falhou"
    storage.update_request(req)
    OffboardingService(settings=settings, writer=writer, directory=directory, storage=storage).run(
        storage.get_request(req.id)
    )
    assert writer.leave_dates[JOAO] == primeira


def test_grupo_do_ad_local_vira_acao_manual():
    from app.core.offboarding import classify_group
    from app.graph.models import Group

    assert "AD local" in classify_group(Group("g", "Sync", on_premises=True))
    assert classify_group(Group("g", "Nuvem")) == ""


def test_gestor_nao_gera_tap_de_colaborador_desligado(c):
    storage = c.app.state.storage
    adm = make_req(storage)
    adm.object_id, adm.status = JOAO, "ativa"
    adm.gestor = adm.gestor.model_copy(update={"id": "u-1"})
    storage.create_request(adm)
    assert adm.id in c.get("/equipe", headers=GESTORA).text
    rid = pedir(c, imediato="on")
    aprovar(c, rid)
    assert adm.id not in c.get("/equipe", headers=GESTORA).text
    resp = c.post(f"/equipe/{adm.id}/acesso-inicial", data={"csrf_token": csrf(c)}, headers=GESTORA)
    assert resp.status_code == 409 and "desligamento" in resp.text
    assert c.app.state.writer.taps == {}


def test_busca_de_colaborador_inclui_desativados(c):
    ativos = c.get("/api/diretorio/usuarios?q=carla", headers=RH).json()
    todos = c.get("/api/diretorio/usuarios?q=carla&desativados=true", headers=RH).json()
    assert ativos == [] and todos[0]["ativo"] is False


def test_corrida_agendador_ativa_enquanto_desligamento_e_aprovado(env):
    """A admissão foi lida antes da aprovação do desligamento imediato."""
    from app.core.workflow import Etapa
    from app.services.offboarding import close_admissions

    settings, storage, directory, _, writer = env
    adm = make_req(storage, idem="adm-2")
    adm.object_id, adm.status = JOAO, "conta_criada"
    adm.data_admissao, adm.data_licenca = date(2026, 1, 1), None
    adm.etapas = [Etapa(chave="criar_usuario", nome="Criar", status="ok")]
    storage.create_request(adm)
    antiga = storage.get_request(adm.id)  # cópia lida pelo agendador

    deslig = agendado(env, imediato=True)
    close_admissions(storage, deslig, Pessoa(oid="oid-ti", nome="TI"))
    assert JOAO in writer.disabled

    from app.services.lifecycle import LifecycleReport

    report = LifecycleReport(executado_em=datetime.now(UTC), dry_run=False)
    motor(env)._process(antiga, date(2026, 9, 30), report)  # consulta atual impede a ativação
    assert f"enable:{JOAO}" not in writer.calls and report.ativadas == []


def test_corrida_desfaz_ativacao_se_gravacao_conflitar(env, monkeypatch):
    from app.core.workflow import Etapa
    from app.storage.errors import ConcurrencyError

    settings, storage, directory, _, writer = env
    adm = make_req(storage, idem="adm-3")
    adm.object_id, adm.status = JOAO, "conta_criada"
    adm.data_admissao, adm.data_licenca = date(2026, 1, 1), None
    adm.etapas = [Etapa(chave="criar_usuario", nome="Criar", status="ok")]
    storage.create_request(adm)
    m = motor(env)
    original = storage.update_request

    def aprova_desligamento_no_meio(req):
        if req.id == adm.id:  # enquanto o agendador ativava, o desligamento foi aprovado
            monkeypatch.setattr(storage, "update_request", original)
            agendado(env, imediato=True)
            raise ConcurrencyError("alterada")
        return original(req)

    monkeypatch.setattr(storage, "update_request", aprova_desligamento_no_meio)
    rel = m.run(today=date(2026, 9, 30), now=bloqueio(env) - timedelta(days=9))
    assert f"enable:{JOAO}" in writer.calls
    assert writer.calls[-1] == f"disable:{JOAO}" and JOAO not in writer.enabled
    assert adm.id not in rel.ativadas


def test_conflito_ao_encerrar_admissao_nao_impede_o_desligamento(c, monkeypatch):
    storage = c.app.state.storage
    adm = make_req(storage)
    adm.object_id, adm.status = JOAO, "conta_criada"
    storage.create_request(adm)
    rid = pedir(c, imediato="on")
    original = storage.update_request
    falhas = []

    def conflita_uma_vez(req):
        if req.id == adm.id and not falhas:
            falhas.append(1)
            from app.storage.errors import ConcurrencyError

            raise ConcurrencyError("alterada")
        return original(req)

    monkeypatch.setattr(storage, "update_request", conflita_uma_vez)
    aprovar(c, rid)
    assert falhas and storage.get_request(adm.id).status == "cancelada"
    assert storage.get_request(rid).status == "desligada"
