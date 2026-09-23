"""Autenticação (quem é o usuário) e autorização (o que ele pode fazer).

Em produção, o login é feito pelo App Service Authentication ("Easy Auth") com o
Microsoft Entra ID. O App Service valida o token e repassa a identidade no cabeçalho
``X-MS-CLIENT-PRINCIPAL`` — que a plataforma remove de requisições externas quando a
autenticação está ativa. Por isso só confiamos nesse cabeçalho se o App Service
informar ``WEBSITE_AUTH_ENABLED=True``.

A autorização é SEMPRE validada aqui no backend, a partir dos App Roles do token.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass, field

from fastapi import Depends, Request

from app.config import Settings
from app.dependencies import get_app_settings

logger = logging.getLogger("m365up.auth")

PRINCIPAL_HEADER = "X-MS-CLIENT-PRINCIPAL"
IDP_HEADER = "X-MS-CLIENT-PRINCIPAL-IDP"

DEV_OBJECT_ID = "00000000-0000-0000-0000-000000000001"
ZERO_GUID = "00000000-0000-0000-0000-000000000000"


class Roles:
    """App Roles definidos no App Registration (valores exatos do token)."""

    SOLICITANTE = "Provisionamento.Solicitante"
    APROVADOR = "Provisionamento.Aprovador"
    ADMINISTRADOR = "Provisionamento.Administrador"

    ALL = frozenset({SOLICITANTE, APROVADOR, ADMINISTRADOR})

    LABELS = {
        SOLICITANTE: "Solicitante (RH)",
        APROVADOR: "Aprovador",
        ADMINISTRADOR: "Administrador",
    }


_CLAIM_TENANT = ("http://schemas.microsoft.com/identity/claims/tenantid", "tid")
_CLAIM_OID = ("http://schemas.microsoft.com/identity/claims/objectidentifier", "oid")
_CLAIM_NAME = ("name",)
_CLAIM_UPN = (
    "preferred_username",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
    "upn",
)
_CLAIM_ROLES = ("roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role")


class NotAuthenticatedError(Exception):
    """Usuário não autenticado (HTTP 401)."""


class ForbiddenError(Exception):
    """Usuário autenticado, mas sem permissão (HTTP 403)."""

    def __init__(self, reason: str = "sem_papel") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    object_id: str
    tenant_id: str
    name: str
    username: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    audience: str = ""

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def portal_roles(self) -> list[str]:
        return sorted(r for r in self.roles if r in Roles.ALL)

    @property
    def role_labels(self) -> list[str]:
        return [Roles.LABELS[r] for r in self.portal_roles]


def _first(claims: dict[str, list[str]], names: tuple[str, ...]) -> str:
    for n in names:
        if claims.get(n):
            return claims[n][0]
    return ""


def parse_client_principal(header_value: str) -> Principal:
    """Decodifica o cabeçalho X-MS-CLIENT-PRINCIPAL (JSON em base64)."""
    try:
        padded = header_value + "=" * (-len(header_value) % 4)
        data = json.loads(base64.b64decode(padded, validate=False))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise NotAuthenticatedError("cabecalho_invalido") from exc
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise NotAuthenticatedError("cabecalho_invalido")

    claims: dict[str, list[str]] = {}
    for c in data["claims"]:
        if isinstance(c, dict) and isinstance(c.get("typ"), str) and isinstance(c.get("val"), str):
            claims.setdefault(c["typ"], []).append(c["val"])

    role_types = set(_CLAIM_ROLES)
    if isinstance(data.get("role_typ"), str):
        role_types.add(data["role_typ"])
    roles = frozenset(v for t in role_types for v in claims.get(t, []))

    oid = _first(claims, _CLAIM_OID)
    tid = _first(claims, _CLAIM_TENANT)
    if not oid or not tid:
        raise NotAuthenticatedError("claims_obrigatorias_ausentes")

    return Principal(
        object_id=oid,
        tenant_id=tid,
        name=_first(claims, _CLAIM_NAME) or _first(claims, _CLAIM_UPN),
        username=_first(claims, _CLAIM_UPN),
        roles=roles,
        audience=_first(claims, ("aud",)),
    )


def _resolve_principal(request: Request, settings: Settings) -> Principal | None:
    if settings.auth_mode == "dev":
        return Principal(
            object_id=DEV_OBJECT_ID,
            tenant_id=settings.azure_tenant_id or ZERO_GUID,
            name=settings.dev_user_name,
            username="dev@localhost",
            roles=settings.dev_roles,
        )

    if not settings.website_auth_enabled:
        # Sem a autenticação do App Service ativa, o cabeçalho poderia ser forjado.
        logger.error("AUTH_MODE=easyauth, mas a autenticação do App Service está desativada")
        return None

    header = request.headers.get(PRINCIPAL_HEADER)
    if not header:
        return None
    if request.headers.get(IDP_HEADER, "aad").lower() != "aad":
        raise ForbiddenError("provedor_nao_permitido")

    principal = parse_client_principal(header)

    if principal.tenant_id.lower() != settings.azure_tenant_id.lower():
        logger.warning("Acesso negado: tenant externo %s", principal.tenant_id)
        raise ForbiddenError("tenant_nao_autorizado")
    if (
        settings.entra_app_client_id
        and principal.audience
        and principal.audience.lower() != settings.entra_app_client_id.lower()
    ):
        logger.warning("Acesso negado: audiência inesperada")
        raise ForbiddenError("audiencia_invalida")
    return principal


def get_optional_principal(
    request: Request, settings: Settings = Depends(get_app_settings)
) -> Principal | None:
    if not hasattr(request.state, "principal"):
        request.state.principal = _resolve_principal(request, settings)
    return request.state.principal


def get_current_principal(
    principal: Principal | None = Depends(get_optional_principal),
) -> Principal:
    if principal is None:
        raise NotAuthenticatedError("nao_autenticado")
    return principal


def require_roles(*roles: str):
    """Dependência que exige pelo menos um dos App Roles informados."""
    unknown = set(roles) - Roles.ALL
    if unknown:
        raise ValueError(f"Papéis desconhecidos: {unknown}")

    def _dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has_any_role(*roles):
            logger.info(
                "Acesso negado a %s: exige %s, possui %s",
                principal.object_id,
                sorted(roles),
                principal.portal_roles,
            )
            raise ForbiddenError("sem_papel")
        return principal

    return _dependency
