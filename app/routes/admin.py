"""Área do Administrador: capacidades do tenant e perfis de onboarding."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.auth import Principal, Roles, require_roles
from app.config import Settings
from app.core.capabilities import detect_capabilities
from app.core.profiles import (
    TIPOS_COLABORADOR,
    OnboardingProfile,
    ProfileValidationError,
    eligible_access_groups,
    eligible_license_groups,
    eligible_skus,
    resolve_selection,
)
from app.core.skus import friendly_sku_name
from app.csrf import verify_csrf
from app.dependencies import get_app_settings, get_directory, get_storage
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError, GraphPermissionError
from app.storage import StorageBackend
from app.templating import templates

router = APIRouter(prefix="/admin", include_in_schema=False)
logger = logging.getLogger("m365up.admin")

AdminDep = Depends(require_roles(Roles.ADMINISTRADOR))


def _graph_error_message(exc: GraphError) -> str:
    if isinstance(exc, GraphPermissionError):
        return (
            "A identidade do portal não tem permissão de leitura no Microsoft Graph. "
            "Rode scripts/Set-GraphPermissions.ps1 e aguarde alguns minutos."
        )
    return "Não foi possível consultar o Microsoft Graph agora. Tente novamente em instantes."


def _render(
    request: Request, name: str, settings: Settings, principal: Principal, status=200, **ctx
):
    return templates.TemplateResponse(
        request,
        name,
        {"settings": settings, "principal": principal, "sku_name": friendly_sku_name, **ctx},
        status_code=status,
    )


# ------------------------------------------------------------------ capacidades
@router.get("", response_class=HTMLResponse)
def overview(
    request: Request,
    refresh: bool = False,
    settings: Settings = Depends(get_app_settings),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> Response:
    try:
        snap = directory.snapshot(refresh=refresh)
    except GraphError as exc:
        logger.warning("Falha ao ler o tenant: %s", exc)
        return _render(
            request,
            "admin.html",
            settings,
            principal,
            status=503,
            erro_graph=_graph_error_message(exc),
        )
    caps = detect_capabilities(
        snap, license_mode=settings.license_mode, tap_lifetime_minutes=settings.tap_lifetime_minutes
    )
    protected = settings.protected_groups
    return _render(
        request,
        "admin.html",
        settings,
        principal,
        snap=snap,
        caps=caps,
        grupos_acesso=eligible_access_groups(snap.groups, protected),
        grupos_licenca=eligible_license_groups(snap.groups, protected),
        protegidos=protected,
    )


@router.get("/capacidades.json")
def overview_json(
    settings: Settings = Depends(get_app_settings),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> JSONResponse:
    try:
        snap = directory.snapshot()
    except GraphError as exc:
        return JSONResponse(status_code=503, content={"erro": _graph_error_message(exc)})
    caps = detect_capabilities(
        snap, license_mode=settings.license_mode, tap_lifetime_minutes=settings.tap_lifetime_minutes
    )
    return JSONResponse(
        {
            "tenant": {"id": snap.organization.id, "nome": snap.organization.display_name},
            "dominios": [d.name for d in snap.domains if d.is_verified],
            "capacidades": caps.__dict__,
            "licencas": [
                {
                    "skuPartNumber": s.sku_part_number,
                    "skuId": s.sku_id,
                    "total": s.enabled_units,
                    "usadas": s.consumed_units,
                    "disponiveis": s.available_units,
                }
                for s in snap.skus
            ],
            "dryRun": settings.dry_run,
        }
    )


# --------------------------------------------------------------------- perfis
@router.get("/perfis", response_class=HTMLResponse)
def list_profiles(
    request: Request,
    ok: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> HTMLResponse:
    return _render(
        request,
        "perfis.html",
        settings,
        principal,
        perfis=storage.list_profiles(),
        tipos=TIPOS_COLABORADOR,
        ok=ok[:20],
    )


def _form_context(directory: DirectoryCache, settings: Settings) -> dict:
    groups = directory.groups()
    return {
        "grupos_acesso": eligible_access_groups(groups, settings.protected_groups),
        "grupos_licenca": eligible_license_groups(groups, settings.protected_groups),
        "skus": eligible_skus(directory.skus()),
        "tipos": TIPOS_COLABORADOR,
    }


def _as_form(perfil) -> dict:
    """Normaliza um perfil salvo (ou rascunho com erro) para o formulário."""
    if perfil is None:
        return {
            "id": None,
            "nome": "",
            "departamento": "",
            "tipo_colaborador": "",
            "grupos_acesso": [],
            "grupo_licenca": "",
            "sku_licenca": "",
            "ativo": True,
        }
    if isinstance(perfil, dict):
        return perfil
    return {
        "id": perfil.id,
        "nome": perfil.nome,
        "departamento": perfil.departamento,
        "tipo_colaborador": perfil.tipo_colaborador,
        "grupos_acesso": [g.id for g in perfil.grupos_acesso],
        "grupo_licenca": perfil.grupo_licenca.id if perfil.grupo_licenca else "",
        "sku_licenca": perfil.sku_licenca.sku_id if perfil.sku_licenca else "",
        "ativo": perfil.ativo,
    }


def _profile_form(request, settings, principal, directory, perfil, erros=None, status=200):
    perfil = _as_form(perfil)
    try:
        ctx = _form_context(directory, settings)
    except GraphError as exc:
        return _render(
            request,
            "admin.html",
            settings,
            principal,
            status=503,
            erro_graph=_graph_error_message(exc),
        )
    return _render(
        request,
        "perfil-form.html",
        settings,
        principal,
        status=status,
        perfil=perfil,
        erros=erros or [],
        **ctx,
    )


@router.get("/perfis/novo", response_class=HTMLResponse)
def new_profile(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> Response:
    return _profile_form(request, settings, principal, directory, None)


@router.get("/perfis/{profile_id}", response_class=HTMLResponse)
def edit_profile(
    profile_id: str,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> Response:
    perfil = storage.get_profile(profile_id)
    if not perfil:
        return RedirectResponse("/admin/perfis", status_code=303)
    return _profile_form(request, settings, principal, directory, perfil)


async def _save(
    request: Request,
    profile_id: str | None,
    settings: Settings,
    storage: StorageBackend,
    directory: DirectoryCache,
    principal: Principal,
) -> Response:
    form = await request.form()
    existing = storage.get_profile(profile_id) if profile_id else None
    if profile_id and not existing:
        return RedirectResponse("/admin/perfis", status_code=303)

    raw = {
        "nome": str(form.get("nome", "")),
        "departamento": str(form.get("departamento", "")),
        "tipo_colaborador": str(form.get("tipo_colaborador", "")),
    }
    erros: list[str] = []
    try:
        # Revalida contra o tenant AGORA (cache renovado), nunca confiando no navegador.
        acesso, grupo_lic, sku = resolve_selection(
            access_group_ids=[str(v) for v in form.getlist("grupos_acesso")],
            license_group_id=str(form.get("grupo_licenca", "")) or None,
            sku_id=str(form.get("sku_licenca", "")) or None,
            groups=directory.groups(refresh=True),
            skus=directory.skus(refresh=True),
            protected=settings.protected_groups,
            license_mode=settings.license_mode,
        )
    except ProfileValidationError as exc:
        erros.extend(exc.erros)
        acesso, grupo_lic, sku = [], None, None
    except GraphError as exc:
        erros.append(_graph_error_message(exc))
        acesso, grupo_lic, sku = [], None, None

    perfil = None
    if not erros:
        try:
            perfil = OnboardingProfile(
                id=existing.id if existing else _new_id(),
                grupos_acesso=acesso,
                grupo_licenca=grupo_lic,
                sku_licenca=sku,
                ativo=form.get("ativo") == "on",
                atualizado_por=principal.object_id,
                atualizado_em=datetime.now(UTC),
                **raw,
            )
        except ValueError as exc:
            erros.append(_friendly_validation(exc))

    if perfil and any(
        p.nome.lower() == perfil.nome.lower() and p.id != perfil.id for p in storage.list_profiles()
    ):
        erros.append("Já existe um perfil com esse nome.")

    if erros:
        draft = {
            **raw,
            "grupos_acesso": form.getlist("grupos_acesso"),
            "grupo_licenca": form.get("grupo_licenca", ""),
            "sku_licenca": form.get("sku_licenca", ""),
            "ativo": form.get("ativo") == "on",
            "id": profile_id,
        }
        return _profile_form(request, settings, principal, directory, draft, erros, status=422)

    storage.save_profile(perfil)
    logger.info("Perfil %s salvo por %s", perfil.id, principal.object_id)
    return RedirectResponse("/admin/perfis?ok=salvo", status_code=303)


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _friendly_validation(exc: ValueError) -> str:
    text = str(exc)
    if "nome" in text:
        return "Nome do perfil inválido (3 a 80 caracteres, sem < > \" ' `)."
    if "departamento" in text:
        return "Departamento inválido (1 a 80 caracteres, sem < > \" ' `)."
    if "tipo_colaborador" in text:
        return "Selecione o tipo de colaborador."
    return "Dados do perfil inválidos."


@router.post("/perfis", dependencies=[Depends(verify_csrf)])
async def create_profile(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> Response:
    return await _save(request, None, settings, storage, directory, principal)


@router.post("/perfis/{profile_id}", dependencies=[Depends(verify_csrf)])
async def update_profile(
    profile_id: str,
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> Response:
    return await _save(request, profile_id, settings, storage, directory, principal)


@router.post("/perfis/{profile_id}/excluir", dependencies=[Depends(verify_csrf)])
def delete_profile(
    profile_id: str,
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> Response:
    if storage.get_profile(profile_id):
        storage.delete_profile(profile_id)
        logger.info("Perfil %s excluído por %s", profile_id, principal.object_id)
    return RedirectResponse("/admin/perfis?ok=excluido", status_code=303)
