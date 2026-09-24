"""Área do gestor: novos colaboradores da equipe e acesso inicial (TAP)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth import Principal, get_current_principal
from app.config import Settings
from app.core.workflow import REQUEST_ID_RE
from app.csrf import verify_csrf
from app.dependencies import get_app_settings, get_graph, get_storage, get_writer
from app.graph.service import GraphService
from app.graph.writer import GraphWriter
from app.services.access import AccessError, generate_initial_access, team_requests
from app.storage import StorageBackend
from app.storage.errors import ConcurrencyError
from app.templating import templates

router = APIRouter(prefix="/equipe", include_in_schema=False)


def _page(request, settings, principal, storage, erro="", status=200):
    return templates.TemplateResponse(
        request,
        "equipe.html",
        {
            "settings": settings,
            "principal": principal,
            "itens": team_requests(storage, principal),
            "erro": erro,
        },
        status_code=status,
    )


@router.get("", response_class=HTMLResponse)
def team(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(get_current_principal),
) -> HTMLResponse:
    return _page(request, settings, principal, storage)


@router.post("/{request_id}/acesso-inicial", dependencies=[Depends(verify_csrf)])
def initial_access(
    request_id: str,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    graph: GraphService = Depends(get_graph),
    writer: GraphWriter = Depends(get_writer),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    req = storage.get_request(request_id) if REQUEST_ID_RE.match(request_id) else None
    if req is None:
        return RedirectResponse("/equipe", status_code=303)
    try:
        codigo, minutos = generate_initial_access(
            req, principal, settings=settings, graph=graph, writer=writer, storage=storage
        )
    except AccessError as exc:
        return _page(request, settings, principal, storage, str(exc), status=409)
    except ConcurrencyError:
        return _page(
            request,
            settings,
            principal,
            storage,
            "A solicitação foi atualizada ao mesmo tempo. Tente de novo.",
            status=409,
        )
    # Exibido uma única vez; a resposta não é armazenada em cache (Cache-Control: no-store).
    return templates.TemplateResponse(
        request,
        "acesso-inicial.html",
        {
            "settings": settings,
            "principal": principal,
            "req": req,
            "codigo": codigo,
            "minutos": minutos,
        },
    )
