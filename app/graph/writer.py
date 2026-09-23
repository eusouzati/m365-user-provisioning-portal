"""Escrita no Microsoft Graph (Sprint 6): criar usuário, definir gestor, adicionar a grupos.

Separada do GraphService (leitura) para que a escrita só exista quando DRY_RUN=false.
Nenhuma senha é registrada em log.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.graph.errors import GraphError
from app.graph.service import MsGraphService

logger = logging.getLogger("m365up.graph.escrita")


class GraphWriter(Protocol):
    dry_run: bool

    def create_user(self, body: dict[str, Any]) -> str:
        """Cria o usuário e devolve o Object ID. ``body`` inclui passwordProfile."""

    def get_user_by_upn(self, upn: str) -> dict[str, Any] | None: ...
    def set_manager(self, user_id: str, manager_id: str) -> None: ...
    def add_group_member(self, group_id: str, user_id: str) -> bool:
        """True se adicionou; False se já era membro."""


class MsGraphWriter(MsGraphService):
    dry_run = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._allow_write = True

    def create_user(self, body: dict[str, Any]) -> str:
        logger.info("Criando usuário %s (desativado)", body.get("userPrincipalName"))
        created = self._request("POST", "users", json=body)
        return created["id"]

    def get_user_by_upn(self, upn: str) -> dict[str, Any] | None:
        try:
            return self._get(
                f"users/{upn}",
                {"$select": "id,userPrincipalName,employeeId,accountEnabled,displayName"},
            )
        except GraphError as exc:
            if exc.status == 404:
                return None
            raise

    def set_manager(self, user_id: str, manager_id: str) -> None:
        self._request(
            "PUT",
            f"users/{user_id}/manager/$ref",
            json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{manager_id}"},
        )

    def add_group_member(self, group_id: str, user_id: str) -> bool:
        try:
            self._request(
                "POST",
                f"groups/{group_id}/members/$ref",
                json={"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"},
            )
            return True
        except GraphError as exc:
            if exc.status == 400 and "already exist" in str(exc).lower():
                return False
            raise


class DryRunWriter:
    """Não altera nada: apenas registra o que seria feito."""

    dry_run = True

    def __init__(self) -> None:
        self.planned: list[str] = []

    def create_user(self, body: dict[str, Any]) -> str:
        self.planned.append(f"criar {body.get('userPrincipalName')}")
        return ""

    def get_user_by_upn(self, upn: str) -> dict[str, Any] | None:
        return None

    def set_manager(self, user_id: str, manager_id: str) -> None:
        self.planned.append(f"gestor {manager_id}")

    def add_group_member(self, group_id: str, user_id: str) -> bool:
        self.planned.append(f"grupo {group_id}")
        return True
