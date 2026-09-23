from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import Principal, get_current_principal

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
