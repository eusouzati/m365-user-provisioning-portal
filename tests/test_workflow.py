from __future__ import annotations

import pytest

from app.core.workflow import Pessoa, WorkflowError, approve, cancel, reject
from app.storage.sqlite import SqliteStorage
from tests.test_storage_contract import make_req

RH = Pessoa(oid="oid-rh", nome="RH")
TI = Pessoa(oid="oid-ti", nome="TI")


@pytest.fixture
def req(tmp_path):
    return make_req(SqliteStorage(str(tmp_path / "w.db")))


def test_aprovar(req):
    approve(req, TI, "ok")
    assert req.status == "aprovada"
    ev = req.historico[-1]
    assert (ev.de, ev.para, ev.ator.oid, ev.comentario) == ("enviada", "aprovada", "oid-ti", "ok")


def test_solicitante_nao_aprova_nem_rejeita_a_propria(req):
    with pytest.raises(WorkflowError, match="não pode aprovar"):
        approve(req, Pessoa(oid="OID-RH", nome="RH"))
    with pytest.raises(WorkflowError, match="não pode rejeitar"):
        reject(req, RH, "motivo qualquer")
    assert req.status == "enviada" and req.historico == []


def test_rejeitar_exige_comentario(req):
    with pytest.raises(WorkflowError, match="motivo"):
        reject(req, TI, "  ok ")
    reject(req, TI, "Cargo  incorreto")
    assert req.status == "rejeitada" and req.historico[-1].comentario == "Cargo incorreto"


def test_nao_transiciona_estado_final(req):
    reject(req, TI, "motivo válido")
    for acao in (
        lambda: approve(req, TI),
        lambda: cancel(req, RH),
        lambda: reject(req, TI, "xxxxx"),
    ):
        with pytest.raises(WorkflowError):
            acao()


def test_cancelar(req):
    with pytest.raises(WorkflowError, match="Somente quem"):
        cancel(req, TI)
    cancel(req, TI, is_admin=True)
    assert req.status == "cancelada"


def test_comentario_limitado(req):
    approve(req, TI, "x" * 900)
    assert len(req.historico[-1].comentario) == 500


# ------------------------------------------------------------ Sprint 8
def test_admissao_aprovada_nao_pode_ser_cancelada(req):
    approve(req, TI)
    with pytest.raises(WorkflowError, match="não pode ser cancelada"):
        cancel(req, RH)


def test_desligamento_agendado_pode_ser_cancelado_ate_comecar(req):
    from app.core.workflow import Etapa, can_cancel

    req.tipo = "desligamento"
    approve(req, TI)
    assert req.status_label == "Desligamento agendado" and req.tipo_label == "Desligamento"
    req.etapas = [Etapa(chave="bloquear", nome="Bloquear", detalhe="Agendada")]
    assert can_cancel(req)
    req.etapas[0].status = "ok"
    assert not can_cancel(req)
    with pytest.raises(WorkflowError):
        cancel(req, RH)


def test_registros_antigos_sao_admissao(req):
    from app.core.workflow import ProvisioningRequest

    antigo = ProvisioningRequest.model_validate_json(
        req.model_dump_json(exclude={"tipo", "data_desligamento"})
    )
    assert antigo.tipo == "admissao" and antigo.data_efetiva == req.data_admissao
