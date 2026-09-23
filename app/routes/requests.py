"""Área do RH: formulário de novo colaborador, revisão e envio (simulado nesta versão)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.auth import Principal, Roles, require_roles
from app.config import Settings
from app.core.profiles import TIPOS_COLABORADOR
from app.core.requests import NewHireForm, friendly_errors
from app.core.workflow import REQUEST_ID_RE, WorkflowError, cancel
from app.csrf import verify_csrf
from app.dependencies import get_app_settings, get_directory, get_graph, get_storage
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError
from app.graph.service import GraphService
from app.services.onboarding import ReviewError, today_in
from app.services.requests_flow import new_request as build_request
from app.services.requests_flow import pessoa, review_form
from app.storage import StorageBackend
from app.storage.errors import ConcurrencyError, DuplicateRequestError
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
    "idem",
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
        idem = dados.get("idem", "")
        review = review_form(
            form,
            settings=settings,
            graph=graph,
            directory=directory,
            storage=storage,
            exclude_idem=idem if _valid_idem(idem) else None,
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
    ok: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = RhDep,
) -> HTMLResponse:
    itens = storage.list_requests(solicitante_oid=principal.object_id)
    return _render(
        request,
        "solicitacoes.html",
        settings,
        principal,
        itens=itens,
        titulo="Minhas solicitações",
        ok=ok[:20],
    )


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
    if not _valid_idem(dados.get("idem", "")):
        dados["idem"] = str(uuid.uuid4())  # uma chave por solicitação: evita duplicidade
    return _render(request, "solicitacao-revisao.html", settings, principal, r=review, dados=dados)


@router.post("/editar", dependencies=[Depends(verify_csrf)])
async def back_to_form(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = RhDep,
) -> Response:
    return _form_page(request, settings, principal, storage, await _read_form(request))


def _valid_idem(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


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
    review, dados = ok
    idem = dados.get("idem", "")
    if not _valid_idem(idem):
        return _form_page(
            request,
            settings,
            principal,
            storage,
            dados,
            ["A revisão expirou. Revise a solicitação novamente."],
            422,
        )
    req = build_request(
        review, settings=settings, storage=storage, principal=principal, idempotency_key=idem
    )
    try:
        storage.create_request(req)
    except DuplicateRequestError as exc:  # duplo clique / reenvio
        return RedirectResponse(f"/solicitacoes/{exc.existing_id}", status_code=303)
    logger.info("Solicitação %s criada por %s", req.id, principal.object_id)
    return RedirectResponse(f"/solicitacoes/{req.id}?ok=enviada", status_code=303)


# ----------------------------------------------------------------- detalhe
ViewerDep = Depends(require_roles(Roles.SOLICITANTE, Roles.APROVADOR, Roles.ADMINISTRADOR))


def load_visible(storage: StorageBackend, request_id: str, principal: Principal):
    """Carrega a solicitação se o usuário puder vê-la (dono, aprovador ou administrador)."""
    from app.auth import ForbiddenError

    req = storage.get_request(request_id) if REQUEST_ID_RE.match(request_id) else None
    if req is None:
        return None
    if not (
        req.eh_do_solicitante(principal.object_id)
        or principal.has_any_role(Roles.APROVADOR, Roles.ADMINISTRADOR)
    ):
        raise ForbiddenError("sem_papel")
    return req


def render_detail(request, settings, principal, req, erros=None, ok="", status=200):
    pode_decidir = (
        req.pendente
        and principal.has_any_role(Roles.APROVADOR)
        and not req.eh_do_solicitante(principal.object_id)
    )
    pode_cancelar = req.pendente and (
        req.eh_do_solicitante(principal.object_id) or principal.has_any_role(Roles.ADMINISTRADOR)
    )
    return _render(
        request,
        "solicitacao-detalhe.html",
        settings,
        principal,
        status=status,
        req=req,
        erros=erros or [],
        ok=ok[:20],
        tipos=TIPOS_COLABORADOR,
        pode_decidir=pode_decidir,
        pode_cancelar=pode_cancelar,
        propria_pendente=req.pendente
        and req.eh_do_solicitante(principal.object_id)
        and principal.has_any_role(Roles.APROVADOR),
    )


@router.get("/{request_id}", response_class=HTMLResponse)
def detail(
    request_id: str,
    request: Request,
    ok: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = ViewerDep,
) -> Response:
    req = load_visible(storage, request_id, principal)
    if req is None:
        return _render(
            request,
            "erro.html",
            settings,
            principal,
            status=404,
            titulo="Solicitação não encontrada",
            mensagem="Verifique o número da solicitação.",
        )
    return render_detail(request, settings, principal, req, ok=ok)


@router.post("/{request_id}/cancelar", dependencies=[Depends(verify_csrf)])
async def cancel_request(
    request_id: str,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = ViewerDep,
) -> Response:
    req = load_visible(storage, request_id, principal)
    if req is None:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    try:
        cancel(
            req,
            pessoa(principal),
            is_admin=principal.has_any_role(Roles.ADMINISTRADOR),
            comentario=str(form.get("comentario", "")),
        )
        storage.update_request(req)
    except WorkflowError as exc:
        return render_detail(
            request, settings, principal, storage.get_request(request_id), [str(exc)], status=409
        )
    except ConcurrencyError:
        return render_detail(
            request,
            settings,
            principal,
            storage.get_request(request_id),
            ["A solicitação foi alterada por outra pessoa. Confira o status."],
            status=409,
        )
    logger.info("Solicitação %s cancelada por %s", request_id, principal.object_id)
    return RedirectResponse(f"/solicitacoes/{request_id}?ok=cancelada", status_code=303)
