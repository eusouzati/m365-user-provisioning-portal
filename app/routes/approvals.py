"""Área do Aprovador: fila de solicitações e decisão (aprovar/rejeitar)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.auth import Principal, Roles, require_roles
from app.config import Settings
from app.core.requests import NewHireForm
from app.core.workflow import WorkflowError, approve, reject
from app.csrf import verify_csrf
from app.dependencies import (
    get_app_settings,
    get_directory,
    get_graph,
    get_storage,
    get_writer,
)
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError
from app.graph.service import GraphService
from app.graph.writer import GraphWriter
from app.routes.requests import load_visible, render_detail, run_provisioning
from app.services.offboarding import (
    build_offboarding_review,
    close_admissions,
    run_offboarding_if_due,
)
from app.services.onboarding import ReviewError
from app.services.requests_flow import pessoa, refresh_from_review, review_form
from app.storage import StorageBackend
from app.storage.errors import ConcurrencyError
from app.templating import templates

router = APIRouter(prefix="/aprovacoes", include_in_schema=False)
logger = logging.getLogger("m365up.aprovacoes")

AprovadorDep = Depends(require_roles(Roles.APROVADOR))


@router.get("", response_class=HTMLResponse)
def queue(
    request: Request,
    ok: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AprovadorDep,
) -> HTMLResponse:
    oid = principal.object_id
    pendentes = [r for r in storage.list_requests(status="enviada") if not r.eh_alvo(oid)]
    recentes = [
        r for r in storage.list_requests(limit=50) if not r.pendente and not r.eh_alvo(oid)
    ][:20]
    return templates.TemplateResponse(
        request,
        "aprovacoes.html",
        {
            "settings": settings,
            "principal": principal,
            "pendentes": pendentes,
            "recentes": recentes,
            "ok": ok[:20],
        },
    )


def _conflict(request, settings, principal, storage, request_id, msg):
    return render_detail(
        request, settings, principal, storage.get_request(request_id), [msg], status=409
    )


@router.post("/{request_id}/aprovar", dependencies=[Depends(verify_csrf)])
async def approve_request(
    request_id: str,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    graph: GraphService = Depends(get_graph),
    directory: DirectoryCache = Depends(get_directory),
    storage: StorageBackend = Depends(get_storage),
    writer: GraphWriter = Depends(get_writer),
    principal: Principal = AprovadorDep,
) -> Response:
    req = load_visible(storage, request_id, principal)
    if req is None:
        return RedirectResponse("/aprovacoes", status_code=303)
    comentario = str((await request.form()).get("comentario", ""))
    if req.eh_desligamento:
        return _approve_offboarding(
            request, req, comentario, settings, graph, directory, storage, writer, principal
        )

    # Revalida contra o estado ATUAL do tenant antes de aprovar.
    try:
        form = NewHireForm.model_validate(req.dados)
        review = review_form(
            form,
            settings=settings,
            graph=graph,
            directory=directory,
            storage=storage,
            exclude_id=req.id,
        )
    except (ValidationError, ReviewError) as exc:
        erros = getattr(exc, "erros", None) or ["Os dados da solicitação não são mais válidos."]
        return render_detail(
            request,
            settings,
            principal,
            req,
            ["Não é possível aprovar: " + e for e in erros],
            status=422,
        )
    except GraphError:
        return render_detail(
            request,
            settings,
            principal,
            req,
            ["Microsoft 365 indisponível. Tente novamente."],
            status=503,
        )

    try:
        mudancas = refresh_from_review(req, review)
        nota = " ".join([comentario.strip(), *mudancas]).strip()
        approve(req, pessoa(principal), nota)
        req = storage.update_request(req)
    except WorkflowError as exc:
        return _conflict(request, settings, principal, storage, request_id, str(exc))
    except ConcurrencyError:
        return _conflict(
            request,
            settings,
            principal,
            storage,
            request_id,
            "A solicitação foi alterada por outra pessoa. Confira o status.",
        )
    logger.info("Solicitação %s aprovada por %s", request_id, principal.object_id)

    # Provisionamento logo após a aprovação (em DRY_RUN, apenas simulado).
    run_provisioning(req, settings=settings, writer=writer, directory=directory, storage=storage)
    return RedirectResponse(f"/solicitacoes/{request_id}?ok=aprovada", status_code=303)


def _approve_offboarding(
    request, req, comentario, settings, graph, directory, storage, writer, principal
) -> Response:
    from app.core.offboarding import OffboardingForm

    if req.object_id.lower() == principal.object_id.lower():
        return render_detail(
            request,
            settings,
            principal,
            req,
            ["Você não pode aprovar o seu próprio desligamento."],
            status=409,
        )
    # Revalida contra o estado ATUAL do tenant (colaborador existe, sem outro pedido em curso).
    try:
        form = OffboardingForm.model_validate(
            {
                "colaborador_id": req.object_id,
                "data_desligamento": req.data_desligamento,
                "imediato": "on" if req.dados.get("imediato") else "",
                "observacao": req.dados.get("observacao", ""),
            }
        )
        build_offboarding_review(
            form,
            settings=settings,
            graph=graph,
            directory=directory,
            storage=storage,
            principal=principal,
            exclude_id=req.id,
        )
    except (ValidationError, ReviewError) as exc:
        erros = getattr(exc, "erros", None) or ["Os dados da solicitação não são mais válidos."]
        # A data pode ter ficado no passado entre o pedido e a aprovação: isso é permitido.
        erros = [e for e in erros if not e.startswith("Último dia de trabalho")]
        if erros:
            return render_detail(
                request,
                settings,
                principal,
                req,
                ["Não é possível aprovar: " + e for e in erros],
                status=422,
            )
    except GraphError:
        return render_detail(
            request,
            settings,
            principal,
            req,
            ["Microsoft 365 indisponível. Tente novamente."],
            status=503,
        )
    try:
        approve(req, pessoa(principal), comentario)
        req = storage.update_request(req)
    except WorkflowError as exc:
        return _conflict(request, settings, principal, storage, req.id, str(exc))
    except ConcurrencyError:
        return _conflict(
            request,
            settings,
            principal,
            storage,
            req.id,
            "A solicitação foi alterada por outra pessoa. Confira o status.",
        )
    logger.info("Desligamento %s aprovado por %s", req.id, principal.object_id)
    # Admissão em andamento da mesma conta (ex.: não compareceu): nunca será ativada.
    for rid in close_admissions(storage, req, pessoa(principal)):
        logger.info("Admissão %s encerrada pelo desligamento %s", rid, req.id)
    try:
        run_offboarding_if_due(
            req, settings=settings, writer=writer, directory=directory, storage=storage
        )
    except ConcurrencyError:
        logger.warning("Desligamento %s alterado durante a execução", req.id)
    return RedirectResponse(f"/solicitacoes/{req.id}?ok=aprovada", status_code=303)


@router.post("/{request_id}/rejeitar", dependencies=[Depends(verify_csrf)])
async def reject_request(
    request_id: str,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AprovadorDep,
) -> Response:
    req = load_visible(storage, request_id, principal)
    if req is None:
        return RedirectResponse("/aprovacoes", status_code=303)
    comentario = str((await request.form()).get("comentario", ""))
    try:
        reject(req, pessoa(principal), comentario)
        storage.update_request(req)
    except WorkflowError as exc:
        return render_detail(
            request, settings, principal, storage.get_request(request_id), [str(exc)], status=422
        )
    except ConcurrencyError:
        return _conflict(
            request,
            settings,
            principal,
            storage,
            request_id,
            "A solicitação foi alterada por outra pessoa. Confira o status.",
        )
    logger.info("Solicitação %s rejeitada por %s", request_id, principal.object_id)
    return RedirectResponse(f"/solicitacoes/{request_id}?ok=rejeitada", status_code=303)
