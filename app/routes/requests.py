"""Área do RH: formulário de novo colaborador, revisão e envio (simulado nesta versão)."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.auth import Principal, Roles, require_roles
from app.config import Settings
from app.core.profiles import TIPOS_COLABORADOR
from app.core.requests import NewHireForm, friendly_errors
from app.csrf import verify_csrf
from app.dependencies import get_app_settings, get_directory, get_graph, get_storage
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError
from app.graph.service import GraphService
from app.services.onboarding import ReviewError, build_review, today_in
from app.storage import StorageBackend
from app.templating import templates

router = APIRouter(prefix="/solicitacoes", include_in_schema=False)
logger = logging.getLogger("m365up.solicitacoes")

RhDep = Depends(require_roles(Roles.SOLICITANTE))

CAMPOS_FORM = (
    "nome",
    "sobrenome",
    "nome_exibicao",
    "matricula",
    "cargo",
    "departamento",
    "empresa",
    "unidade",
    "cidade",
    "estado",
    "pais",
    "data_admissao",
    "gestor_id",
    "gestor_nome",
    "tipo_colaborador",
    "perfil_id",
)


def _render(request, name, settings, principal, status=200, **ctx):
    return templates.TemplateResponse(
        request, name, {"settings": settings, "principal": principal, **ctx}, status_code=status
    )


def _form_page(request, settings, principal, storage, dados, erros=None, status=200):
    perfis = [p for p in storage.list_profiles() if p.ativo]
    return _render(
        request,
        "solicitacao-form.html",
        settings,
        principal,
        status=status,
        dados=dados,
        erros=erros or [],
        perfis=perfis,
        tipos=TIPOS_COLABORADOR,
        data_min=(today_in(settings) - timedelta(days=settings.hire_date_past_days)).isoformat(),
        data_max=(today_in(settings) + timedelta(days=settings.hire_date_future_days)).isoformat(),
    )


async def _read_form(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(form.get(k, ""))[:512] for k in CAMPOS_FORM}


async def _review_or_errors(request, settings, principal, graph, directory, storage):
    dados = await _read_form(request)
    try:
        form = NewHireForm.model_validate(dados)
    except ValidationError as exc:
        return None, _form_page(
            request, settings, principal, storage, dados, friendly_errors(exc), status=422
        )
    try:
        review = build_review(
            form, settings=settings, graph=graph, directory=directory, storage=storage
        )
    except ReviewError as exc:
        return None, _form_page(request, settings, principal, storage, dados, exc.erros, 422)
    except GraphError:
        logger.exception("Falha no Graph ao revisar solicitação")
        return None, _form_page(
            request,
            settings,
            principal,
            storage,
            dados,
            ["Não foi possível consultar o Microsoft 365 agora. Tente novamente."],
            503,
        )
    return (review, dados), None


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    principal: Principal = RhDep,
) -> HTMLResponse:
    return _render(request, "solicitacoes.html", settings, principal)


@router.get("/novo", response_class=HTMLResponse)
def new_request(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = RhDep,
) -> HTMLResponse:
    return _form_page(request, settings, principal, storage, {"pais": "Brasil"})


@router.post("/revisar", dependencies=[Depends(verify_csrf)])
async def review_request(
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
    return _render(request, "solicitacao-revisao.html", settings, principal, r=review, dados=dados)


@router.post("/editar", dependencies=[Depends(verify_csrf)])
async def back_to_form(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = RhDep,
) -> Response:
    return _form_page(request, settings, principal, storage, await _read_form(request))


@router.post("/enviar", dependencies=[Depends(verify_csrf)])
async def submit_request(
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
    review, _ = ok
    logger.info(
        "Solicitação simulada por %s (perfil %s) — nada gravado, nada criado",
        principal.object_id,
        review.perfil.id,
    )
    # Sprint 4: sempre simulação. A gravação e o fluxo de aprovação chegam na Sprint 5.
    return _render(request, "solicitacao-simulada.html", settings, principal, r=review)
