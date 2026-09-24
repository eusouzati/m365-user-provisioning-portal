"""Contrato de armazenamento: o mesmo conjunto de testes roda em SQLite e,
quando disponível, no Azurite (emulador do Azure Table Storage)."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import date

import pytest

from app.core.workflow import (
    ContaPlanejada,
    GestorSnapshot,
    PerfilSnapshot,
    Pessoa,
    ProvisioningRequest,
)
from app.storage.errors import ConcurrencyError, DuplicateRequestError
from app.storage.sqlite import SqliteStorage

AZURITE = os.environ.get("AZURITE_CONNECTION_STRING", "")


def backends():
    yield pytest.param("sqlite", id="sqlite")
    yield pytest.param(
        "azure",
        id="azurite",
        marks=pytest.mark.skipif(not AZURITE, reason="AZURITE_CONNECTION_STRING não definido"),
    )


@pytest.fixture(params=list(backends()))
def storage(request, tmp_path):
    if request.param == "sqlite":
        return SqliteStorage(str(tmp_path / "c.db"))
    from app.storage.azure_table import AzureTableStorage

    s = AzureTableStorage(connection_string=AZURITE)
    for t in ("solicitacoes", "perfis", "auditoria", "estado"):
        s._client.delete_table(t)
    s._tables.clear()
    return s


def make_req(storage, day=date(2026, 9, 23), oid="oid-rh", idem=None) -> ProvisioningRequest:
    return ProvisioningRequest(
        id=storage.next_request_id(day),
        idempotency_key=idem or str(uuid.uuid4()),
        solicitante=Pessoa(oid=oid, nome="RH"),
        dados={"nome": "João"},
        conta=ContaPlanejada(
            display_name="João Silva",
            given_name="João",
            surname="Silva",
            user_principal_name="joao.silva@contoso.com",
            mail="joao.silva@contoso.com",
            mail_nickname="joao.silva",
        ),
        perfil=PerfilSnapshot(id="p", nome="Perfil"),
        gestor=GestorSnapshot(id="u-1", nome="Ana", upn="ana@contoso.com"),
        data_admissao=date(2026, 10, 3),
        data_licenca=date(2026, 10, 2),
    )


def test_request_id_sequencial_por_dia(storage):
    d = date(2026, 9, 23)
    assert storage.next_request_id(d) == "REQ-20260923-0001"
    assert storage.next_request_id(d) == "REQ-20260923-0002"
    assert storage.next_request_id(date(2026, 9, 24)) == "REQ-20260924-0001"


def test_request_id_concorrente_sem_repeticao(storage):
    ids, lock = [], threading.Lock()

    def worker():
        rid = storage.next_request_id(date(2026, 1, 1))
        with lock:
            ids.append(rid)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 10


def test_criar_ler_listar(storage):
    a = make_req(storage, oid="OID-A")
    b = make_req(storage, oid="oid-b")
    storage.create_request(a)
    storage.create_request(b)
    assert storage.get_request(a.id).conta.user_principal_name == "joao.silva@contoso.com"
    assert [r.id for r in storage.list_requests()] == [b.id, a.id]  # mais recente primeiro
    assert [r.id for r in storage.list_requests(solicitante_oid="oid-a")] == [a.id]
    assert storage.list_requests(status="aprovada") == []
    assert storage.get_request("REQ-19990101-0001") is None


def test_idempotencia(storage):
    a = make_req(storage, idem="chave-1")
    storage.create_request(a)
    b = make_req(storage, idem="chave-1")
    with pytest.raises(DuplicateRequestError) as exc:
        storage.create_request(b)
    assert exc.value.existing_id == a.id
    assert len(storage.list_requests()) == 1


def test_concorrencia_otimista(storage):
    a = make_req(storage)
    storage.create_request(a)
    leitura1 = storage.get_request(a.id)
    leitura2 = storage.get_request(a.id)
    leitura1.status = "aprovada"
    salvo = storage.update_request(leitura1)
    assert salvo.versao == 2
    leitura2.status = "rejeitada"
    with pytest.raises(ConcurrencyError):
        storage.update_request(leitura2)
    assert storage.get_request(a.id).status == "aprovada"
    assert [r.id for r in storage.list_requests(status="aprovada")] == [a.id]


# ------------------------------------------------------------ Sprint 9
def test_auditoria_ordem_e_periodo(storage):
    from datetime import UTC, datetime, timedelta

    from app.core.audit import AuditEvent

    base = datetime(2026, 8, 31, 23, 0, tzinfo=UTC)
    for i in range(5):  # atravessa a virada do mês (partições diferentes no Azure)
        storage.append_audit(
            AuditEvent(
                em=base + timedelta(hours=i), ator_oid="o", ator_nome="A", acao=f"a{i}", alvo="R"
            )
        )
    todos = storage.list_audit(inicio=base - timedelta(days=1), fim=base + timedelta(days=1))
    assert [e.acao for e in todos] == ["a4", "a3", "a2", "a1", "a0"]
    janela = storage.list_audit(inicio=base + timedelta(hours=1), fim=base + timedelta(hours=3))
    assert [e.acao for e in janela] == ["a2", "a1"]
    assert len(storage.list_audit(inicio=base - timedelta(days=1), limit=2)) == 2


def test_estado(storage):
    assert storage.get_state("ultimo_ciclo") is None
    storage.set_state("ultimo_ciclo", {"analisadas": 1})
    storage.set_state("ultimo_ciclo", {"analisadas": 2})
    assert storage.get_state("ultimo_ciclo") == {"analisadas": 2}
