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
from app.core.workflow import STATUS_LABELS, offboarded_ids
from app.csrf import verify_csrf
from app.dependencies import get_app_settings, get_directory, get_storage, get_writer
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError, GraphPermissionError
from app.graph.writer import GraphWriter
from app.services.lifecycle import LifecycleService
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


# ---------------------------------------------------------------- solicitações
@router.get("/solicitacoes", response_class=HTMLResponse)
def all_requests(
    request: Request,
    status: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> HTMLResponse:
    itens = [
        r
        for r in storage.list_requests(
            status=status if status in STATUS_LABELS else None, limit=500
        )
        if not r.eh_alvo(principal.object_id)
    ]
    return _render(
        request,
        "solicitacoes.html",
        settings,
        principal,
        itens=itens,
        titulo="Todas as solicitações",
        aba="solicitacoes",
        desligados=offboarded_ids(storage.list_requests(limit=1000)),
    )


@router.post("/ciclo-de-vida", dependencies=[Depends(verify_csrf)])
def run_lifecycle_now(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    directory: DirectoryCache = Depends(get_directory),
    writer: GraphWriter = Depends(get_writer),
    principal: Principal = AdminDep,
) -> HTMLResponse:
    """Executa agora o motor de ciclo de vida (o mesmo que o agendador chama de hora em hora)."""
    logger.info("Ciclo de vida executado manualmente por %s", principal.object_id)
    report = LifecycleService(
        settings=settings, writer=writer, directory=directory, storage=storage
    ).run()
    return _render(
        request,
        "solicitacoes.html",
        settings,
        principal,
        itens=[r for r in storage.list_requests(limit=500) if not r.eh_alvo(principal.object_id)],
        titulo="Todas as solicitações",
        aba="solicitacoes",
        ciclo=report,
        desligados=offboarded_ids(storage.list_requests(limit=1000)),
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


# ---------------------------------------------------------------------- painel
@router.get("/painel", response_class=HTMLResponse)
def dashboard(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    directory: DirectoryCache = Depends(get_directory),
    principal: Principal = AdminDep,
) -> HTMLResponse:
    from app.services.dashboard import build_dashboard

    return _render(
        request,
        "painel.html",
        settings,
        principal,
        d=build_dashboard(storage, directory, settings),
        aba="painel",
    )


# ------------------------------------------------------------------- auditoria
AUDIT_LIMIT, AUDIT_EXPORT_LIMIT = 500, 20000


def _audit_query(storage, settings, acao, alvo, ator, de, ate, limit):
    from datetime import date as _date
    from datetime import time, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(settings.timezone)

    def _dia(v: str):
        try:
            return _date.fromisoformat(v) if v else None
        except ValueError:
            return None

    d_de, d_ate = _dia(de), _dia(ate)
    inicio = datetime.combine(d_de, time(0), tz) if d_de else None
    fim = datetime.combine(d_ate + timedelta(days=1), time(0), tz) if d_ate else None
    # Busca com folga e filtra aqui; com filtros, a folga é maior.
    folga = 20 if (acao or alvo or ator) else 1
    eventos = storage.list_audit(inicio=inicio, fim=fim, limit=min(limit * folga, 50_000))
    alvo_q, ator_q = alvo.strip().lower(), ator.strip().lower()
    filtrados = [
        e
        for e in eventos
        if (not acao or e.acao == acao)
        and (not alvo_q or alvo_q in e.alvo.lower())
        and (not ator_q or ator_q in e.ator_nome.lower())
    ][:limit]
    filtros = {"acao": acao, "alvo": alvo, "ator": ator, "de": de, "ate": ate}
    return filtrados, {k: v[:100] for k, v in filtros.items()}


@router.get("/auditoria", response_class=HTMLResponse)
def audit_log(
    request: Request,
    acao: str = "",
    alvo: str = "",
    ator: str = "",
    de: str = "",
    ate: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> HTMLResponse:
    from app.core.audit import ACOES

    eventos, filtros = _audit_query(
        storage, settings, acao if acao in ACOES else "", alvo, ator, de, ate, AUDIT_LIMIT
    )
    return _render(
        request,
        "auditoria.html",
        settings,
        principal,
        eventos=eventos,
        filtros=filtros,
        acoes=ACOES,
        limite=AUDIT_LIMIT,
        aba="auditoria",
    )


def _csv_cell(v: str) -> str:
    """Evita injeção de fórmulas ao abrir no Excel."""
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@router.get("/auditoria.csv")
def audit_export(
    acao: str = "",
    alvo: str = "",
    ator: str = "",
    de: str = "",
    ate: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> Response:
    import csv
    import io
    from zoneinfo import ZoneInfo

    from app.core.audit import ACOES, AuditEvent

    eventos, filtros = _audit_query(
        storage, settings, acao if acao in ACOES else "", alvo, ator, de, ate, AUDIT_EXPORT_LIMIT
    )
    tz = ZoneInfo(settings.timezone)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["data_hora", "acao", "descricao", "alvo", "tipo", "ator", "ator_id", "detalhe"])
    for e in eventos:
        w.writerow(
            [
                e.em.astimezone(tz).strftime("%d/%m/%Y %H:%M:%S"),
                e.acao,
                e.acao_label,
                e.alvo,
                e.tipo,
                _csv_cell(e.ator_nome),
                e.ator_oid,
                _csv_cell(e.detalhe),
            ]
        )
    storage.append_audit(
        AuditEvent(
            ator_oid=principal.object_id,
            ator_nome=principal.name or principal.username,
            acao="auditoria.exportada",
            # só quais filtros foram usados (o texto digitado pode conter nomes)
            detalhe=f"{len(eventos)} evento(s)"
            + "".join(f"; filtro {k}" for k, v in filtros.items() if v),
        )
    )
    nome = f"auditoria-{datetime.now(tz):%Y%m%d-%H%M}.csv"
    return Response(
        content="\ufeff" + buf.getvalue(),  # BOM: acentos corretos no Excel
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nome}"',
            "Cache-Control": "no-store",
        },
    )


# ------------------------------------------------------------------ privacidade
@router.get("/privacidade", response_class=HTMLResponse)
def privacy_admin(
    request: Request,
    ok: str = "",
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> HTMLResponse:
    from app.services.privacy import eligible

    return _render(
        request,
        "admin-privacidade.html",
        settings,
        principal,
        elegiveis=eligible(storage.list_requests(limit=100_000), settings),
        ok=ok[:20],
        aba="privacidade",
    )


@router.post("/privacidade/anonimizar", dependencies=[Depends(verify_csrf)])
def privacy_run(
    settings: Settings = Depends(get_app_settings),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = AdminDep,
) -> Response:
    from app.services.privacy import run_retention
    from app.services.requests_flow import pessoa

    feitos = run_retention(storage, settings, ator=pessoa(principal))
    logger.info("LGPD: %s anonimizada(s) por %s", len(feitos), principal.object_id)
    return RedirectResponse(f"/admin/privacidade?ok={len(feitos)}", status_code=303)
