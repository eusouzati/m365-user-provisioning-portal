"""Implementação falsa do GraphService (desenvolvimento local e testes).

Dados fictícios da organização "Contoso". Nenhuma chamada de rede.
"""

from __future__ import annotations

from app.graph.models import (
    AddressConflict,
    Domain,
    Group,
    Organization,
    SubscribedSku,
    TapPolicy,
    UserSummary,
)

SKU_E3 = "05e9a617-0261-4cee-bb44-138d3ef5d965"
SKU_P1 = "078d2b04-f1bd-4111-bbd4-b4b1b354cef4"


class FakeGraphService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.organization = Organization(
            "00000000-0000-0000-0000-00000000c0de", "Contoso (simulado)", False, "BR"
        )
        self.domains = [
            Domain("contoso.onmicrosoft.com", False, True),
            Domain("contoso.com", True, True),
        ]
        self.skus = [
            SubscribedSku(
                SKU_E3,
                "SPE_E3",
                "Enabled",
                25,
                20,
                ("EXCHANGE_S_ENTERPRISE", "AAD_PREMIUM", "TEAMS1"),
            ),
            SubscribedSku(SKU_P1, "AAD_PREMIUM", "Enabled", 5, 5, ("AAD_PREMIUM",)),
        ]
        self.tap_policy: TapPolicy | None = TapPolicy(True, 60, 480, False)
        self.groups = [
            Group("g-fin", "Financeiro", "Equipe financeira"),
            Group("g-rh", "RH", "Recursos Humanos"),
            Group("g-ti", "TI", "Tecnologia"),
            Group("g-vpn", "VPN - Usuários", "Acesso VPN"),
            Group("g-lic-e3", "Licença - Microsoft 365 E3", assigned_license_sku_ids=(SKU_E3,)),
            Group("g-dyn", "Todos (dinâmico)", is_dynamic=True),
            Group("g-admins", "Admins privilegiados", is_role_assignable=True),
            Group("g-portal-adm", "M365UP-Administradores", "Papel do portal"),
            Group(
                "g-all",
                "All Company",
                security_enabled=False,
                mail_enabled=True,
                is_m365=True,
                mail="allcompany@contoso.com",
            ),
        ]
        self.users = [
            UserSummary(
                "u-1",
                "Ana Gestora",
                "ana.gestora@contoso.com",
                "ana.gestora@contoso.com",
                "Gerente Financeira",
                "Financeiro",
            ),
            UserSummary(
                "u-2",
                "Bruno Lima",
                "bruno.lima@contoso.com",
                "bruno.lima@contoso.com",
                "Coordenador de TI",
                "TI",
            ),
            UserSummary(
                "u-3",
                "João Silva",
                "joao.silva@contoso.com",
                "joao.silva@contoso.com",
                "Analista",
                "Financeiro",
                employee_id="1001",
            ),
            UserSummary(
                "u-4",
                "Carla Desligada",
                "carla@contoso.com",
                "carla@contoso.com",
                "Gerente",
                "RH",
                account_enabled=False,
            ),
        ]

    def get_organization(self) -> Organization:
        self.calls.append("organization")
        return self.organization

    def list_domains(self) -> list[Domain]:
        self.calls.append("domains")
        return list(self.domains)

    def list_subscribed_skus(self) -> list[SubscribedSku]:
        self.calls.append("skus")
        return list(self.skus)

    def get_tap_policy(self) -> TapPolicy | None:
        self.calls.append("tap")
        return self.tap_policy

    def list_groups(self) -> list[Group]:
        self.calls.append("groups")
        return sorted(self.groups, key=lambda g: g.display_name.lower())

    def get_user(self, user_id: str) -> UserSummary | None:
        return next((u for u in self.users if user_id in (u.id, u.user_principal_name)), None)

    def search_users(self, query: str, top: int = 10) -> list[UserSummary]:
        q = query.strip().lower()
        if len(q) < 2:
            return []
        hits = []
        for u in self.users:
            texto = f"{u.display_name} {u.user_principal_name}".lower()
            if u.account_enabled and q in texto:
                hits.append(u)
        return hits[:top]

    def find_address_conflicts(self, address: str, mail_nickname: str) -> list[AddressConflict]:
        a, n = address.lower(), mail_nickname.lower()
        out = []
        for u in self.users:
            if a in (u.user_principal_name.lower(), u.mail.lower()):
                out.append(AddressConflict("usuario", u.id, u.display_name, "userPrincipalName"))
            elif u.user_principal_name.split("@")[0].lower() == n:
                out.append(AddressConflict("usuario", u.id, u.display_name, "mailNickname"))
        for g in self.groups:
            if g.mail and (g.mail.lower() == a or g.mail.split("@")[0].lower() == n):
                out.append(AddressConflict("grupo", g.id, g.display_name, "mail"))
        return out

    def find_users_by_employee_id(self, employee_id: str) -> list[UserSummary]:
        return [u for u in self.users if u.employee_id and u.employee_id == employee_id]


class FakeGraphWriter:
    """Escritor em memória para desenvolvimento local e testes (DRY_RUN=false + fake)."""

    dry_run = False

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.managers: dict[str, str] = {}
        self.members: dict[str, set[str]] = {}
        self.fail_groups: set[str] = set()
        self.fail_create = False
        self.calls: list[str] = []

    def create_user(self, body: dict) -> str:
        self.calls.append("create_user")
        if self.fail_create:
            from app.graph.errors import GraphError

            raise GraphError("Graph 400 Request_BadRequest: falha simulada", 400)
        uid = f"new-{len(self.users) + 1}"
        self.users[uid] = dict(body)
        return uid

    def get_user_by_upn(self, upn: str) -> dict | None:
        for uid, u in self.users.items():
            if u["userPrincipalName"].lower() == upn.lower():
                return {"id": uid, **{k: v for k, v in u.items() if k != "passwordProfile"}}
        return None

    def set_manager(self, user_id: str, manager_id: str) -> None:
        self.calls.append("set_manager")
        self.managers[user_id] = manager_id

    def add_group_member(self, group_id: str, user_id: str) -> bool:
        self.calls.append(f"add:{group_id}")
        if group_id in self.fail_groups:
            from app.graph.errors import GraphError

            raise GraphError("Graph 403 Authorization_RequestDenied: falha simulada", 403)
        s = self.members.setdefault(group_id, set())
        if user_id in s:
            return False
        s.add(user_id)
        return True
