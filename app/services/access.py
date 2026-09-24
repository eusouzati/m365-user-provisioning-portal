"""Acesso inicial: o GESTOR gera, no dia da admissão, um Temporary Access Pass (TAP).

- Somente o gestor registrado na solicitação pode gerar (validado no backend).
- Somente para contas já ativadas (status "ativa").
- TAP de uso único, com validade limitada pela política do tenant.
- O código é exibido UMA vez e nunca é registrado, armazenado ou enviado para logs.
  O histórico guarda apenas "TAP gerado por X".
"""

from __future__ import annotations

import logging

from app.auth import Principal
from app.config import Settings
from app.core.workflow import ProvisioningRequest, note
from app.graph.errors import GraphError
from app.graph.service import GraphService
from app.graph.writer import GraphWriter
from app.services.requests_flow import pessoa
from app.storage import StorageBackend

logger = logging.getLogger("m365up.acesso")

TEAM_STATUSES = frozenset({"conta_criada", "licenciada", "ativa"})


class AccessError(RuntimeError):
    """Mensagem em português, para o usuário."""


def is_manager(req: ProvisioningRequest, principal: Principal) -> bool:
    return req.gestor.id.lower() == principal.object_id.lower()


def team_requests(storage: StorageBackend, principal: Principal) -> list[ProvisioningRequest]:
    return [
        r
        for r in storage.list_requests(limit=1000)
        if r.status in TEAM_STATUSES and is_manager(r, principal)
    ]


def tap_lifetime(settings: Settings, graph: GraphService) -> int:
    policy = graph.get_tap_policy()
    if not policy or not policy.enabled:
        raise AccessError(
            "A política de Temporary Access Pass está desabilitada no tenant. "
            "Peça ao administrador para habilitá-la."
        )
    minutos = settings.tap_lifetime_minutes
    if policy.max_lifetime_minutes:
        minutos = min(minutos, policy.max_lifetime_minutes)
    return max(minutos, 10)


def _tap_error_message(exc: GraphError) -> str:
    """Mensagem útil ao gestor, com o motivo informado pelo Microsoft Graph (nunca o código)."""
    if exc.status == 403:
        return (
            "O portal não tem permissão para gerar o acesso inicial "
            "(UserAuthenticationMethod.ReadWrite.All). Peça ao administrador para executar "
            "Set-GraphPermissions.ps1 -Nivel ciclo-de-vida e reiniciar o App Service. "
            f"Detalhe: {exc}"
        )
    if 400 <= exc.status < 500:
        return (
            "O Microsoft 365 recusou o acesso inicial. Verifique se a política de "
            "Temporary Access Pass está habilitada e inclui este usuário (Entra ID → "
            f"Métodos de autenticação → Temporary Access Pass). Detalhe: {exc}"
        )
    return (
        "Não foi possível gerar o acesso inicial agora. Tente novamente em instantes. "
        f"Detalhe: {exc}"
    )


def generate_initial_access(
    req: ProvisioningRequest,
    principal: Principal,
    *,
    settings: Settings,
    graph: GraphService,
    writer: GraphWriter,
    storage: StorageBackend,
) -> tuple[str, int]:
    """Devolve (código TAP, validade em minutos)."""
    if not is_manager(req, principal):
        raise AccessError("Somente o gestor do colaborador pode gerar o acesso inicial.")
    if req.status != "ativa":
        raise AccessError("A conta ainda não foi ativada. O acesso inicial fica disponível no D0.")
    if writer.dry_run:
        raise AccessError("DRY_RUN ativo: nenhum acesso inicial é gerado.")
    minutos = tap_lifetime(settings, graph)
    try:
        codigo = writer.create_temporary_access_pass(req.object_id, minutos)
    except GraphError as exc:
        logger.warning("Falha ao gerar TAP de %s: %s", req.id, exc)
        raise AccessError(_tap_error_message(exc)) from exc
    note(
        req,
        pessoa(principal),
        f"Acesso inicial (TAP) gerado pelo gestor — uso único, válido por {minutos} min.",
    )
    storage.update_request(req)
    logger.info("TAP gerado para %s pelo gestor %s", req.id, principal.object_id)
    return codigo, minutos
