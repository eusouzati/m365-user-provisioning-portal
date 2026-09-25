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
from app.core.workflow import ProvisioningRequest, note, offboarded_ids
from app.graph.errors import GraphError, mensagem_usuario
from app.graph.service import GraphService
from app.graph.writer import GraphWriter
from app.services.requests_flow import pessoa
from app.storage import StorageBackend

logger = logging.getLogger("m365up.acesso")

TEAM_STATUSES = frozenset({"conta_criada", "licenciada", "ativa"})


class AccessError(RuntimeError):
    """Mensagem em português, para o usuário."""


def is_manager(req: ProvisioningRequest, principal: Principal) -> bool:
    return not req.eh_desligamento and req.gestor.id.lower() == principal.object_id.lower()


def team_requests(storage: StorageBackend, principal: Principal) -> list[ProvisioningRequest]:
    todas = storage.list_requests(limit=1000)
    desligados = offboarded_ids(todas)
    return [
        r
        for r in todas
        if r.status in TEAM_STATUSES
        and is_manager(r, principal)
        and r.object_id.lower() not in desligados
    ]


def tap_lifetime(settings: Settings, graph: GraphService) -> int:
    policy = graph.get_tap_policy()
    if not policy or not policy.enabled:
        raise AccessError(
            "O acesso inicial por código temporário está desativado no Microsoft 365 da "
            "organização. Peça ao administrador para habilitá-lo."
        )
    minutos = settings.tap_lifetime_minutes
    if policy.max_lifetime_minutes:
        minutos = min(minutos, policy.max_lifetime_minutes)
    return max(minutos, 10)


def _tap_error_message(exc: GraphError) -> str:
    """Mensagem simples ao gestor; a orientação técnica vai para o log (nunca o código)."""
    if exc.status == 403:
        logger.warning(
            "TAP 403: conceda UserAuthenticationMethod.ReadWrite.All "
            "(Set-GraphPermissions.ps1 -Nivel ciclo-de-vida) e reinicie o App Service: %s",
            exc,
        )
        return mensagem_usuario(exc, "gerar o acesso inicial")
    if 400 <= exc.status < 500:
        logger.warning(
            "TAP recusado: confira a política Temporary Access Pass (Entra ID → Métodos de "
            "autenticação) e se ela inclui o usuário: %s",
            exc,
        )
        return (
            "O Microsoft 365 recusou o código de acesso para este colaborador. Peça ao "
            f"administrador para conferir a política de acesso temporário (código {exc.status})."
        )
    return "Não foi possível gerar o acesso inicial agora. Tente novamente em instantes."


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
    if req.object_id.lower() in offboarded_ids(storage.list_requests(limit=1000)):
        raise AccessError("Este colaborador está em desligamento: o acesso inicial não é gerado.")
    if req.status != "ativa":
        raise AccessError(
            "A conta ainda não foi ativada. O acesso inicial fica disponível no dia da admissão."
        )
    if writer.dry_run:
        raise AccessError("Modo simulação ativo: nenhum acesso inicial é gerado.")
    minutos = tap_lifetime(settings, graph)
    try:
        codigo = writer.create_temporary_access_pass(req.object_id, minutos)
    except GraphError as exc:
        logger.warning("Falha ao gerar TAP de %s: %s", req.id, exc)
        raise AccessError(_tap_error_message(exc)) from exc
    note(
        req,
        pessoa(principal),
        f"Acesso inicial gerado pelo gestor — uso único, válido por {minutos} min.",
    )
    storage.update_request(req)
    logger.info("TAP gerado para %s pelo gestor %s", req.id, principal.object_id)
    return codigo, minutos
