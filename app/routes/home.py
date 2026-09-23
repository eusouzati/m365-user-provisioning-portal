from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import Principal, Roles, get_current_principal, require_roles
from app.config import Settings
from app.dependencies import get_app_settings
from app.templating import templates

router = APIRouter(include_in_schema=False)


def _page(request: Request, name: str, settings: Settings, principal: Principal, **ctx):
    return templates.TemplateResponse(
        request, name, {"settings": settings, "principal": principal, **ctx}
    )


def _building(request: Request, settings: Settings, principal: Principal, titulo: str, sprint: int):
    ctx = {"titulo": titulo, "sprint": sprint}
    return _page(request, "em-construcao.html", settings, principal, **ctx)


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(get_current_principal),
) -> HTMLResponse:
    return _page(request, "index.html", settings, principal)


@router.get("/aprovacoes", response_class=HTMLResponse)
def aprovacoes(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_roles(Roles.APROVADOR)),
) -> HTMLResponse:
    return _building(request, settings, principal, "Aprovações", 5)
