"""Escrita no Microsoft Graph: criar usuário, gestor, grupos (Sprint 6); licença direta,
ativação e Temporary Access Pass (Sprint 7); bloqueio, revogação de sessões, data de
desligamento e remoção de grupos/licenças (Sprint 8). Nada aqui exclui usuários.

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

    # Sprint 7 — ciclo de vida
    def assign_license(self, user_id: str, sku_id: str) -> None: ...
    def enable_user(self, user_id: str) -> None: ...
    def create_temporary_access_pass(self, user_id: str, lifetime_minutes: int) -> str:
        """Gera um TAP de uso único e devolve o código. Remove TAP anterior, se houver."""

    # Sprint 8 — desligamento
    def disable_user(self, user_id: str) -> None: ...
    def revoke_sessions(self, user_id: str) -> None: ...
    def set_leave_date(self, user_id: str, leave_utc_iso: str) -> None: ...
    def remove_group_member(self, group_id: str, user_id: str) -> bool:
        """True se removeu; False se já não era membro."""

    def remove_license(self, user_id: str, sku_id: str) -> None: ...


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

    def assign_license(self, user_id: str, sku_id: str) -> None:
        self._request(
            "POST",
            f"users/{user_id}/assignLicense",
            json={"addLicenses": [{"skuId": sku_id, "disabledPlans": []}], "removeLicenses": []},
        )

    def enable_user(self, user_id: str) -> None:
        self._request("PATCH", f"users/{user_id}", json={"accountEnabled": True})

    def create_temporary_access_pass(self, user_id: str, lifetime_minutes: int) -> str:
        base = f"users/{user_id}/authentication/temporaryAccessPassMethods"
        # Só pode existir um TAP por usuário: remove o anterior antes de gerar outro.
        for tap in self._get(base).get("value", []):
            self._request("DELETE", f"{base}/{tap['id']}")
        created = self._request(
            "POST", base, json={"lifetimeInMinutes": lifetime_minutes, "isUsableOnce": True}
        )
        logger.info("TAP gerado para o usuário %s (código não registrado)", user_id)
        return created["temporaryAccessPass"]

    # ------------------------------------------------------ desligamento
    def disable_user(self, user_id: str) -> None:
        logger.info("Bloqueando o usuário %s", user_id)
        self._request("PATCH", f"users/{user_id}", json={"accountEnabled": False})

    def revoke_sessions(self, user_id: str) -> None:
        self._request("POST", f"users/{user_id}/revokeSignInSessions")

    def set_leave_date(self, user_id: str, leave_utc_iso: str) -> None:
        self._request("PATCH", f"users/{user_id}", json={"employeeLeaveDateTime": leave_utc_iso})

    def remove_group_member(self, group_id: str, user_id: str) -> bool:
        try:
            self._request("DELETE", f"groups/{group_id}/members/{user_id}/$ref")
            return True
        except GraphError as exc:
            if exc.status == 404:
                return False
            raise

    def remove_license(self, user_id: str, sku_id: str) -> None:
        self._request(
            "POST",
            f"users/{user_id}/assignLicense",
            json={"addLicenses": [], "removeLicenses": [sku_id]},
        )


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

    def assign_license(self, user_id: str, sku_id: str) -> None:
        self.planned.append(f"licenca {sku_id}")

    def enable_user(self, user_id: str) -> None:
        self.planned.append(f"ativar {user_id}")

    def create_temporary_access_pass(self, user_id: str, lifetime_minutes: int) -> str:
        self.planned.append(f"tap {user_id}")
        return ""

    def disable_user(self, user_id: str) -> None:
        self.planned.append(f"bloquear {user_id}")

    def revoke_sessions(self, user_id: str) -> None:
        self.planned.append(f"revogar {user_id}")

    def set_leave_date(self, user_id: str, leave_utc_iso: str) -> None:
        self.planned.append(f"saida {leave_utc_iso}")

    def remove_group_member(self, group_id: str, user_id: str) -> bool:
        self.planned.append(f"remover {group_id}")
        return True

    def remove_license(self, user_id: str, sku_id: str) -> None:
        self.planned.append(f"remover licenca {sku_id}")
