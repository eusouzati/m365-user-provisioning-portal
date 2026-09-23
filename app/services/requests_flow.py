"""Criação e transições de solicitações (sem escrita no Microsoft 365)."""

from __future__ import annotations

import logging

from app.auth import Principal
from app.config import Settings
from app.core.requests import NewHireForm
from app.core.workflow import (
    FINAL_STATUSES,
    ContaPlanejada,
    GestorSnapshot,
    PerfilSnapshot,
    Pessoa,
    ProvisioningRequest,
)
from app.graph.directory import DirectoryCache
from app.graph.service import GraphService
from app.services.onboarding import Review, build_review, today_in
from app.storage import StorageBackend

logger = logging.getLogger("m365up.fluxo")


def pessoa(principal: Principal) -> Pessoa:
    return Pessoa(oid=principal.object_id, nome=principal.name or principal.username)


def reservations(
    storage: StorageBackend, exclude_id: str | None = None, exclude_idem: str | None = None
):
    """UPNs e matrículas de solicitações em andamento (não finais)."""
    upns: set[str] = set()
    matriculas: dict[str, str] = {}
    for r in storage.list_requests(limit=1000):
        if r.status in FINAL_STATUSES or r.id == exclude_id:
            continue
        if exclude_idem and r.idempotency_key == exclude_idem:  # reenvio da mesma solicitação
            continue
        upns.add(r.conta.user_principal_name.lower())
        if m := r.dados.get("matricula"):
            matriculas[str(m)] = r.id
    return frozenset(upns), matriculas


def review_form(
    form: NewHireForm,
    *,
    settings: Settings,
    graph: GraphService,
    directory: DirectoryCache,
    storage: StorageBackend,
    exclude_id: str | None = None,
    exclude_idem: str | None = None,
) -> Review:
    upns, matriculas = reservations(storage, exclude_id, exclude_idem)
    return build_review(
        form,
        settings=settings,
        graph=graph,
        directory=directory,
        storage=storage,
        reserved_upns=upns,
        reserved_employee_ids=matriculas,
    )


def _conta(review: Review) -> ContaPlanejada:
    n = review.names
    return ContaPlanejada(
        display_name=n.display_name,
        given_name=n.given_name,
        surname=n.surname,
        user_principal_name=n.user_principal_name,
        mail=n.mail,
        mail_nickname=n.mail_nickname,
    )


def _perfil(review: Review) -> PerfilSnapshot:
    p = review.perfil
    return PerfilSnapshot(
        id=p.id,
        nome=p.nome,
        grupos_acesso=[g.model_dump() for g in p.grupos_acesso],
        grupo_licenca=p.grupo_licenca.model_dump() if p.grupo_licenca else None,
        sku_licenca=p.sku_licenca.model_dump() if p.sku_licenca else None,
    )


def new_request(
    review: Review,
    *,
    settings: Settings,
    storage: StorageBackend,
    principal: Principal,
    idempotency_key: str,
) -> ProvisioningRequest:
    from app.core.workflow import Evento

    req = ProvisioningRequest(
        id=storage.next_request_id(today_in(settings)),
        idempotency_key=idempotency_key,
        solicitante=pessoa(principal),
        dados=review.form.model_dump(mode="json"),
        conta=_conta(review),
        perfil=_perfil(review),
        gestor=GestorSnapshot(
            id=review.gestor.id,
            nome=review.gestor.display_name,
            upn=review.gestor.user_principal_name,
        ),
        data_admissao=review.data_ativacao,
        data_licenca=review.data_licenca,
    )
    req.historico.append(Evento(em=req.criado_em, ator=req.solicitante, de=None, para="enviada"))
    return req


def refresh_from_review(req: ProvisioningRequest, review: Review) -> list[str]:
    """Atualiza a solicitação com a revalidação feita na aprovação; devolve as mudanças."""
    mudancas = []
    nova = _conta(review)
    if nova.user_principal_name != req.conta.user_principal_name:
        mudancas.append(
            f"UPN alterado de {req.conta.user_principal_name} para {nova.user_principal_name} "
            "(endereço original ficou indisponível)."
        )
    req.conta = nova
    req.perfil = _perfil(review)
    req.gestor = GestorSnapshot(
        id=review.gestor.id, nome=review.gestor.display_name, upn=review.gestor.user_principal_name
    )
    req.data_licenca = review.data_licenca
    return mudancas
