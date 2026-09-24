"""LGPD: retenção e anonimização dos dados pessoais das solicitações (Sprint 9).

Depois de LGPD_RETENTION_DAYS dias da conclusão (status final), a solicitação perde os
dados pessoais do colaborador: nome, UPN, e-mail, matrícula, cargo, gestor, comentários
e detalhes das etapas. Ficam o número, o tipo, o status, as datas, o Object ID do Entra
(pseudônimo, necessário para rastrear o que foi feito na conta) e quem solicitou/aprovou
(responsabilização). A trilha de auditoria não contém dados pessoais do colaborador.

A conta no Microsoft 365 NÃO é alterada — isso é só sobre os dados guardados no portal.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.core.audit import redact, safe_step_name
from app.core.workflow import (
    ANON,
    ANON_NOTE,
    ETAPA_LABELS,
    FINAL_STATUSES,
    SISTEMA,
    ContaPlanejada,
    GestorSnapshot,
    Pessoa,
    ProvisioningRequest,
    note,
)
from app.storage import StorageBackend
from app.storage.errors import ConcurrencyError

logger = logging.getLogger("m365up.lgpd")

MAX_PER_RUN = 200
LIST_LIMIT = 100_000  # as mais antigas (as que vencem) também precisam ser lidas


def eligible(
    requests: list[ProvisioningRequest], settings: Settings, now: datetime | None = None
) -> list[ProvisioningRequest]:
    if settings.lgpd_retention_days <= 0:
        return []
    limite = (now or datetime.now(UTC)) - timedelta(days=settings.lgpd_retention_days)
    return [
        r
        for r in requests
        if r.status in FINAL_STATUSES and r.anonimizado_em is None and r.atualizado_em < limite
    ]


def anonymize(
    req: ProvisioningRequest, dias: int, ator: Pessoa | None = None
) -> ProvisioningRequest:
    tipo = req.dados.get("tipo_colaborador", "") if not req.eh_desligamento else ""
    req.dados = {"tipo_colaborador": tipo} if tipo else {}
    req.conta = ContaPlanejada(
        display_name=ANON,
        given_name="",
        surname="",
        user_principal_name=ANON,
        mail="",
        mail_nickname="",
    )
    req.gestor = GestorSnapshot(id="", nome=ANON if req.gestor.nome else "", upn="")
    for ev in req.historico:
        if not ev.comentario:
            continue
        # Comentários de pessoas saem; os do sistema ficam sem e-mails e nomes.
        ev.comentario = redact(ev.comentario) if ev.ator.oid == SISTEMA.oid else "[removido]"
    for e in req.etapas:
        e.detalhe = ""
        e.nome = safe_step_name(e.chave, e.nome)
        if e.chave == "definir_gestor":
            e.nome = ETAPA_LABELS["definir_gestor"]
    req.anonimizado_em = datetime.now(UTC)
    note(req, ator or SISTEMA, f"{ANON_NOTE} (LGPD — retenção de {dias} dias).")
    return req


def run_retention(
    storage: StorageBackend,
    settings: Settings,
    now: datetime | None = None,
    ator: Pessoa | None = None,
) -> list[str]:
    """Anonimiza o que venceu. Devolve os números das solicitações anonimizadas."""
    feitos: list[str] = []
    if settings.lgpd_retention_days <= 0:
        return feitos
    todas = storage.list_requests(limit=LIST_LIMIT)
    for req in eligible(todas, settings, now)[:MAX_PER_RUN]:
        try:
            storage.update_request(anonymize(req, settings.lgpd_retention_days, ator))
            feitos.append(req.id)
        except ConcurrencyError:
            continue  # alterada agora; fica para a próxima execução
        except Exception:
            logger.exception("LGPD: falha ao anonimizar %s", req.id)
    if feitos:
        logger.info("LGPD: %s solicitação(ões) anonimizada(s)", len(feitos))
    return feitos
