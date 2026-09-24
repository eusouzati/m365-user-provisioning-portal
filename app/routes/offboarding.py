"""Área do RH: pedido de desligamento (formulário, revisão e envio)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.auth import Principal, Roles, require_roles
from app.config import Settings
from app.core.offboarding import OffboardingForm, friendly_errors
from app.csrf import verify_csrf
from app.dependencies import get_app_settings, get_directory, get_graph, get_storage
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError
from app.graph.service import GraphService
from app.services.offboarding import build_offboarding_review, new_offboarding_request
from app.services.onboarding import ReviewError, today_in
from app.storage import StorageBackend
from app.storage.errors import DuplicateRequestError
from app.templating import templates

router = APIRouter(prefix="/desligamentos", include_in_schema=False)
logger = logging.getLogger("m365up.desligamentos")

RhDep = Depends(require_roles(Roles.SOLICITANTE))
CAMPOS = (
    "colaborador_id",
    "colaborador_nome",
    "data_desligamento",
    "imediato",
    "observacao",
    "idem",
)


def _render(request, name, settings, principal, status=200, **ctx):
    return templates.TemplateResponse(
        request, name, {"settings": settings, "principal": principal, **ctx}, status_code=status
    )


def _form_page(request, settings, principal, dados, erros=None, status=200):
    hoje = today_in(settings)
    return _render(
        request,
        "desligamento-form.html",
        settings,
        principal,
        status=status,
        dados=dados,
        erros=erros or [],
        data_min=(hoje - timedelta(days=settings.hire_date_past_days)).isoformat(),
        data_max=(hoje + timedelta(days=settings.hire_date_future_days)).isoformat(),
    )


def _valid_idem(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


async def _read_form(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(form.get(k, ""))[:600] for k in CAMPOS}


async def _review_or_errors(request, settings, principal, graph, directory, storage):
    dados = await _read_form(request)
    try:
        form = OffboardingForm.model_validate(dados)
    except ValidationError as exc:
        return None, _form_page(request, settings, principal, dados, friendly_errors(exc), 422)
    idem = dados.get("idem", "")
    try:
        review = build_offboarding_review(
            form,
            settings=settings,
            graph=graph,
            directory=directory,
            storage=storage,
            principal=principal,
            exclude_idem=idem if _valid_idem(idem) else None,
        )
    except ReviewError as exc:
        return None, _form_page(request, settings, principal, dados, exc.erros, 422)
    except GraphError:
        logger.exception("Falha no Graph ao revisar desligamento")
        return None, _form_page(
            request,
            settings,
            principal,
            dados,
            ["Não foi possível consultar o Microsoft 365 agora. Tente novamente."],
            503,
        )
    return (review, dados), None


@router.get("/novo", response_class=HTMLResponse)
def new_offboarding(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    principal: Principal = RhDep,
) -> HTMLResponse:
    return _form_page(request, settings, principal, {})


@router.post("/revisar", dependencies=[Depends(verify_csrf)])
async def review_offboarding(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    graph: GraphService = Depends(get_graph),
    directory: DirectoryCache = Depends(get_directory),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = RhDep,
) -> Response:
    ok, erro = await _review_or_errors(request, settings, principal, graph, directory, storage)
    if erro:
        return erro
    review, dados = ok
    if not _valid_idem(dados.get("idem", "")):
        dados["idem"] = str(uuid.uuid4())
    return _render(request, "desligamento-revisao.html", settings, principal, r=review, dados=dados)


@router.post("/editar", dependencies=[Depends(verify_csrf)])
async def back_to_form(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    principal: Principal = RhDep,
) -> Response:
    return _form_page(request, settings, principal, await _read_form(request))


@router.post("/enviar", dependencies=[Depends(verify_csrf)])
async def submit_offboarding(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    graph: GraphService = Depends(get_graph),
    directory: DirectoryCache = Depends(get_directory),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = RhDep,
) -> Response:
    # Recalcula tudo: o que o navegador mostrou na revisão não é confiável.
    ok, erro = await _review_or_errors(request, settings, principal, graph, directory, storage)
    if erro:
        return erro
    review, dados = ok
    idem = dados.get("idem", "")
    if not _valid_idem(idem):
        return _form_page(
            request, settings, principal, dados, ["A revisão expirou. Revise novamente."], 422
        )
    req = new_offboarding_request(
        review, settings=settings, storage=storage, principal=principal, idempotency_key=idem
    )
    try:
        storage.create_request(req)
    except DuplicateRequestError as exc:
        return RedirectResponse(f"/solicitacoes/{exc.existing_id}", status_code=303)
    logger.info("Desligamento %s criado por %s", req.id, principal.object_id)
    return RedirectResponse(f"/solicitacoes/{req.id}?ok=enviada", status_code=303)
