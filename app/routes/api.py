from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.auth import Principal, Roles, get_current_principal, require_roles
from app.dependencies import get_graph
from app.graph.errors import GraphError
from app.graph.service import GraphService

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/me")
def me(principal: Principal = Depends(get_current_principal)) -> dict:
    """Identidade e papéis do usuário atual (útil para diagnóstico)."""
    return {
        "objectId": principal.object_id,
        "tenantId": principal.tenant_id,
        "name": principal.name,
        "username": principal.username,
        "roles": principal.portal_roles,
    }


# ------------------------------------------------------------------ diretório
# Usado pelo formulário de novo colaborador (Sprint 4). Somente leitura.

_DirectoryRoles = Depends(require_roles(Roles.SOLICITANTE, Roles.ADMINISTRADOR))


@router.get("/diretorio/usuarios")
def search_users(
    q: str = Query(min_length=2, max_length=64),
    desativados: bool = False,
    graph: GraphService = Depends(get_graph),
    principal: Principal = _DirectoryRoles,
) -> JSONResponse:
    """Busca de usuários: ativos (gestor) ou também desativados (desligamento)."""
    try:
        users = graph.search_users(q, top=10, include_disabled=desativados)
    except GraphError:
        return JSONResponse(status_code=503, content={"erro": "graph_indisponivel"})
    return JSONResponse(
        [
            {
                "id": u.id,
                "nome": u.display_name,
                "upn": u.user_principal_name,
                "cargo": u.job_title,
                "departamento": u.department,
                "ativo": u.account_enabled,
            }
            for u in users
        ]
    )


@router.get("/diretorio/endereco-disponivel")
def address_available(
    endereco: str = Query(min_length=3, max_length=256, pattern=r"^[^@\s]+@[^@\s]+$"),
    graph: GraphService = Depends(get_graph),
    principal: Principal = _DirectoryRoles,
) -> JSONResponse:
    """Verifica se UPN/e-mail/alias já existem em usuários ou grupos."""
    nickname = endereco.split("@", 1)[0]
    try:
        conflicts = graph.find_address_conflicts(endereco, nickname)
    except GraphError:
        return JSONResponse(status_code=503, content={"erro": "graph_indisponivel"})
    return JSONResponse(
        {
            "endereco": endereco.lower(),
            "disponivel": not conflicts,
            "conflitos": [{"tipo": c.object_type, "atributo": c.matched} for c in conflicts],
        }
    )
