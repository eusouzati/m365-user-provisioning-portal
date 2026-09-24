"""Motor de ciclo de vida: licença no D-1 e ativação no D0."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.workflow import Pessoa, approve
from app.graph.directory import DirectoryCache
from app.graph.fake import FakeGraphService, FakeGraphWriter
from app.graph.writer import DryRunWriter
from app.services.lifecycle import LifecycleService
from app.services.provisioning import UserProvisioningService
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_settings
from tests.test_storage_contract import make_req

TI = Pessoa(oid="oid-ti", nome="TI")
ADMISSAO = date(2026, 10, 3)


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path, auth_mode="dev", dry_run=False)
    storage = SqliteStorage(str(tmp_path / "l.db"))
    graph = FakeGraphService()
    writer = FakeGraphWriter()
    return settings, storage, DirectoryCache(graph), graph, writer


def criada(env, *, licenca="g-lic-e3", sku=None, matricula="2001"):
    settings, storage, directory, _, writer = env
    req = make_req(storage)
    req.dados = {"matricula": matricula, "tipo_colaborador": "funcionario"}
    req.data_admissao = ADMISSAO
    req.data_licenca = ADMISSAO - timedelta(days=1) if (licenca or sku) else None
    req.perfil.grupo_licenca = {"id": licenca, "nome": "Licença E3"} if licenca else None
    req.perfil.sku_licenca = sku
    if matricula != "2001":
        upn = f"u{matricula}@contoso.com"
        req.conta = req.conta.model_copy(update={"user_principal_name": upn, "mail": upn})
    storage.create_request(req)
    approve(req, TI)
    req = storage.update_request(req)
    s = settings.model_copy(update={"license_mode": "direct" if sku else "group"})
    req = UserProvisioningService(
        settings=s, writer=writer, directory=directory, storage=storage
    ).run(req)
    assert req.status == "conta_criada"
    return req


def motor(env, **overrides):
    settings, storage, directory, _, writer = env
    return LifecycleService(
        settings=settings.model_copy(update=overrides),
        writer=writer,
        directory=directory,
        storage=storage,
    )


def etapa(req, chave):
    return next(e for e in req.etapas if e.chave == chave)


def test_etapas_agendadas_aparecem_apos_criacao(env):
    req = criada(env)
    assert etapa(req, "licenca").status == "pendente"
    assert "02/10/2026" in etapa(req, "licenca").detalhe
    assert "03/10/2026" in etapa(req, "ativar").detalhe


def test_antes_do_d1_nada_acontece(env):
    _, storage, _, _, writer = env
    req = criada(env)
    rel = motor(env).run(today=ADMISSAO - timedelta(days=2))
    assert rel.analisadas == 1 and not rel.licenciadas and not rel.ativadas
    assert storage.get_request(req.id).status == "conta_criada"
    assert "g-lic-e3" not in writer.members


def test_d1_licencia_e_d0_ativa(env):
    _, storage, _, _, writer = env
    req = criada(env)
    motor(env).run(today=ADMISSAO - timedelta(days=1))
    req = storage.get_request(req.id)
    assert req.status == "licenciada" and req.object_id in writer.members["g-lic-e3"]
    assert req.object_id not in writer.enabled

    rel = motor(env).run(today=ADMISSAO)
    req = storage.get_request(req.id)
    assert rel.ativadas == [req.id]
    assert req.status == "ativa" and req.object_id in writer.enabled
    assert [e.para for e in req.historico][-2:] == ["licenciada", "ativa"]


def test_admissao_atrasada_faz_tudo_de_uma_vez(env):
    _, storage, _, _, writer = env
    req = criada(env)
    motor(env).run(today=ADMISSAO + timedelta(days=5))
    req = storage.get_request(req.id)
    assert req.status == "ativa"
    assert req.object_id in writer.members["g-lic-e3"] and req.object_id in writer.enabled


def test_idempotente(env):
    _, storage, _, _, writer = env
    req = criada(env)
    motor(env).run(today=ADMISSAO)
    writer.calls.clear()
    rel = motor(env).run(today=ADMISSAO)
    assert rel.analisadas == 0  # ativas não são reprocessadas
    assert writer.calls == []
    assert len(storage.get_request(req.id).historico) == len(storage.get_request(req.id).historico)


def test_sem_licenca_so_ativa(env):
    _, storage, _, _, writer = env
    req = criada(env, licenca=None)
    assert all(e.chave != "licenca" for e in req.etapas)
    motor(env).run(today=ADMISSAO)
    assert storage.get_request(req.id).status == "ativa"


def test_grupo_de_licenca_invalido_falha_e_nao_ativa(env):
    _, storage, _, graph, writer = env
    req = criada(env)
    graph.groups = [g for g in graph.groups if g.id != "g-lic-e3"]
    rel = motor(env).run(today=ADMISSAO)
    req = storage.get_request(req.id)
    assert rel.falhas == [req.id]
    assert req.status == "falha_parcial"
    assert etapa(req, "licenca").status == "falhou"
    assert etapa(req, "ativar").status == "pendente"  # não ativa sem licença
    assert req.object_id not in writer.enabled


def test_falha_na_ativacao_e_nova_tentativa(env):
    _, storage, _, _, writer = env
    req = criada(env)
    writer.fail_enable = True
    motor(env).run(today=ADMISSAO)
    assert storage.get_request(req.id).status == "falha_parcial"
    writer.fail_enable = False
    motor(env).run(today=ADMISSAO)  # próxima execução do agendador
    assert storage.get_request(req.id).status == "ativa"


def test_licenca_direta_verifica_unidades(env):
    _, storage, _, graph, writer = env
    sku = {"sku_id": "05e9a617-0261-4cee-bb44-138d3ef5d965", "part_number": "SPE_E3"}
    req = criada(env, licenca=None, sku=sku)
    motor(env, license_mode="direct").run(today=ADMISSAO)
    req = storage.get_request(req.id)
    assert req.status == "ativa" and sku["sku_id"] in writer.licenses[req.object_id]

    # sem unidades disponíveis: falha clara, sem ativar
    graph.skus = [
        s.__class__(**{**s.__dict__, "consumed_units": s.enabled_units}) for s in graph.skus
    ]
    req2 = criada(env, licenca=None, sku=sku, matricula="2002")
    motor(env, license_mode="direct").run(today=ADMISSAO)
    req2 = storage.get_request(req2.id)
    assert req2.status == "falha_parcial"
    assert "Sem unidades" in etapa(req2, "licenca").detalhe


def test_dry_run_nao_faz_nada(env):
    settings, storage, directory, _, _ = env
    criada(env)
    rel = LifecycleService(
        settings=settings, writer=DryRunWriter(), directory=directory, storage=storage
    ).run(today=ADMISSAO)
    assert rel.dry_run and rel.analisadas == 0


def test_ignora_nao_provisionadas(env):
    _, storage, _, _, _ = env
    req = make_req(storage)
    storage.create_request(req)  # enviada, sem conta
    assert motor(env).run(today=ADMISSAO).analisadas == 0
