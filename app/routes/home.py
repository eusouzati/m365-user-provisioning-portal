from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import Principal, Roles, get_current_principal
from app.config import Settings
from app.core.workflow import FINAL_STATUSES
from app.dependencies import get_app_settings, get_storage
from app.services.access import team_requests
from app.storage import StorageBackend
from app.templating import templates

router = APIRouter(include_in_schema=False)


def _page(request: Request, name: str, settings: Settings, principal: Principal, **ctx):
    return templates.TemplateResponse(
        request, name, {"settings": settings, "principal": principal, **ctx}
    )


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(get_current_principal),
    storage: StorageBackend = Depends(get_storage),
) -> HTMLResponse:
    pendentes = minhas = 0
    if principal.has_any_role(Roles.APROVADOR):
        pendentes = sum(
            1
            for r in storage.list_requests(status="enviada")
            if not r.eh_do_solicitante(principal.object_id)
        )
    if principal.has_any_role(Roles.SOLICITANTE):
        minhas = sum(
            1
            for r in storage.list_requests(solicitante_oid=principal.object_id)
            if r.status not in FINAL_STATUSES
        )
    equipe = team_requests(storage, principal)
    return _page(
        request,
        "index.html",
        settings,
        principal,
        pendentes=pendentes,
        minhas=minhas,
        equipe_ativa=sum(1 for r in equipe if r.status == "ativa"),
        equipe_total=len(equipe),
    )
