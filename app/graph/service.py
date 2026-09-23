"""GraphService — única camada do portal que conversa com o Microsoft Graph.

Sprint 3: SOMENTE LEITURA. Qualquer método HTTP diferente de GET é bloqueado.
Autenticação: Managed Identity (``DefaultAzureCredential``), sem segredos.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Protocol

import httpx

from app.graph.errors import GraphError, GraphPermissionError, ReadOnlyViolationError
from app.graph.models import (
    AddressConflict,
    Domain,
    Group,
    Organization,
    SubscribedSku,
    TapPolicy,
    UserSummary,
)

logger = logging.getLogger("m365up.graph")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
RETRY_STATUS = {429, 500, 502, 503, 504}

_USER_FIELDS = "id,displayName,userPrincipalName,mail,jobTitle,department,accountEnabled,employeeId"
_GROUP_FIELDS = (
    "id,displayName,description,securityEnabled,mailEnabled,groupTypes,"
    "isAssignableToRole,assignedLicenses,mail"
)


class GraphService(Protocol):
    def get_organization(self) -> Organization: ...
    def list_domains(self) -> list[Domain]: ...
    def list_subscribed_skus(self) -> list[SubscribedSku]: ...
    def get_tap_policy(self) -> TapPolicy | None: ...
    def list_groups(self) -> list[Group]: ...
    def get_user(self, user_id: str) -> UserSummary | None: ...
    def search_users(self, query: str, top: int = 10) -> list[UserSummary]: ...
    def find_address_conflicts(self, address: str, mail_nickname: str) -> list[AddressConflict]: ...
    def find_users_by_employee_id(self, employee_id: str) -> list[UserSummary]: ...


def odata_str(value: str) -> str:
    """Escapa um literal de string OData (aspas simples duplicadas)."""
    return value.replace("'", "''")


def sanitize_search(value: str) -> str:
    """Remove caracteres que quebrariam a sintaxe de $search."""
    return re.sub(r'["\\]', "", value).strip()[:64]


def _user(d: dict[str, Any]) -> UserSummary:
    return UserSummary(
        id=d["id"],
        display_name=d.get("displayName") or "",
        user_principal_name=d.get("userPrincipalName") or "",
        mail=d.get("mail") or "",
        job_title=d.get("jobTitle") or "",
        department=d.get("department") or "",
        account_enabled=bool(d.get("accountEnabled", True)),
        employee_id=d.get("employeeId") or "",
    )


def _group(d: dict[str, Any]) -> Group:
    types = d.get("groupTypes") or []
    return Group(
        id=d["id"],
        display_name=d.get("displayName") or "",
        description=d.get("description") or "",
        security_enabled=bool(d.get("securityEnabled")),
        mail_enabled=bool(d.get("mailEnabled")),
        is_m365="Unified" in types,
        is_dynamic="DynamicMembership" in types,
        is_role_assignable=bool(d.get("isAssignableToRole")),
        assigned_license_sku_ids=tuple(
            a["skuId"] for a in (d.get("assignedLicenses") or []) if a.get("skuId")
        ),
        mail=d.get("mail") or "",
    )


class MsGraphService:
    """Implementação real sobre HTTP (httpx)."""

    def __init__(
        self,
        credential: Any,
        client: httpx.Client | None = None,
        max_retries: int = 4,
        max_items: int = 5000,
        sleep=time.sleep,
    ) -> None:
        self._credential = credential
        self._client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self._max_retries = max_retries
        self._max_items = max_items
        self._sleep = sleep
        self._token: str | None = None
        self._token_exp = 0.0
        self._allow_write = False  # somente MsGraphWriter habilita escrita

    # ------------------------------------------------------------------ HTTP
    def _bearer(self) -> str:
        if not self._token or time.time() > self._token_exp - 120:
            tok = self._credential.get_token(GRAPH_SCOPE)
            self._token, self._token_exp = tok.token, float(tok.expires_on)
        return self._token

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
        advanced: bool = False,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        is_read = method == "GET"
        if not is_read and not self._allow_write:
            raise ReadOnlyViolationError(f"Escrita bloqueada no Graph: {method} {url}")
        if not url.startswith("https://"):
            url = f"{GRAPH_BASE}/{url.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._bearer()}"}
        if advanced:
            headers["ConsistencyLevel"] = "eventual"

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(method, url, params=params, headers=headers, json=json)
            except httpx.TransportError as exc:
                # Escrita com falha de rede é ambígua: não repetir às cegas.
                if not is_read or attempt >= self._max_retries:
                    raise GraphError(f"Falha de rede no Graph: {exc}") from exc
                self._sleep(min(2**attempt, 20))
                continue

            retryable = RETRY_STATUS if is_read else {429}  # 429 = não processado
            if resp.status_code in retryable and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After", "")
                delay = int(retry_after) if retry_after.isdigit() else 2**attempt
                logger.warning(
                    "Graph %s em %s; nova tentativa em %ss", resp.status_code, url, delay
                )
                self._sleep(min(delay, 30))
                continue

            if resp.status_code == 404:
                raise GraphError("Objeto não encontrado", 404, "NotFound")
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error", {})
                except ValueError:
                    err = {}
                code, msg = err.get("code", ""), err.get("message", resp.text[:200])
                cls = GraphPermissionError if resp.status_code == 403 else GraphError
                raise cls(f"Graph {resp.status_code} {code}: {msg}", resp.status_code, code)
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        raise GraphError("Limite de tentativas excedido")  # pragma: no cover

    def _get(self, path: str, params: dict[str, str] | None = None, advanced: bool = False):
        return self._request("GET", path, params, advanced)

    def _get_all(
        self, path: str, params: dict[str, str] | None = None, advanced: bool = False
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = self._get(path, params, advanced)
        while True:
            items.extend(page.get("value", []))
            nxt = page.get("@odata.nextLink")
            if not nxt or len(items) >= self._max_items:
                break
            if not nxt.startswith(GRAPH_BASE):
                raise GraphError("nextLink inesperado recebido do Graph")
            page = self._get(nxt, None, advanced)
        return items[: self._max_items]

    # ----------------------------------------------------------- operações
    def get_organization(self) -> Organization:
        org = self._get(
            "organization",
            {"$select": "id,displayName,onPremisesSyncEnabled,countryLetterCode"},
        )["value"][0]
        return Organization(
            id=org["id"],
            display_name=org.get("displayName") or "",
            on_premises_sync_enabled=bool(org.get("onPremisesSyncEnabled")),
            country=org.get("countryLetterCode") or "",
        )

    def list_domains(self) -> list[Domain]:
        return [
            Domain(d["id"], bool(d.get("isDefault")), bool(d.get("isVerified")))
            for d in self._get_all("domains")
        ]

    def list_subscribed_skus(self) -> list[SubscribedSku]:
        out = []
        for s in self._get_all("subscribedSkus"):
            plans = tuple(
                p["servicePlanName"]
                for p in s.get("servicePlans", [])
                if p.get("provisioningStatus") == "Success"
            )
            out.append(
                SubscribedSku(
                    sku_id=s["skuId"],
                    sku_part_number=s.get("skuPartNumber") or "",
                    capability_status=s.get("capabilityStatus") or "",
                    enabled_units=int((s.get("prepaidUnits") or {}).get("enabled") or 0),
                    consumed_units=int(s.get("consumedUnits") or 0),
                    service_plans=plans,
                    applies_to=s.get("appliesTo") or "User",
                )
            )
        return out

    def get_tap_policy(self) -> TapPolicy | None:
        try:
            d = self._get(
                "policies/authenticationMethodsPolicy/authenticationMethodConfigurations/"
                "TemporaryAccessPass"
            )
        except GraphError as exc:
            if exc.status == 404:
                return None
            raise
        return TapPolicy(
            enabled=d.get("state") == "enabled",
            default_lifetime_minutes=int(d.get("defaultLifetimeInMinutes") or 0),
            max_lifetime_minutes=int(d.get("maximumLifetimeInMinutes") or 0),
            is_usable_once=bool(d.get("isUsableOnce")),
        )

    def list_groups(self) -> list[Group]:
        items = self._get_all("groups", {"$select": _GROUP_FIELDS, "$top": "999"})
        return sorted((_group(g) for g in items), key=lambda g: g.display_name.lower())

    def get_user(self, user_id: str) -> UserSummary | None:
        if not re.fullmatch(r"[0-9a-fA-F-]{36}|[^/\s?#]+@[^/\s?#]+", user_id):
            return None
        try:
            return _user(self._get(f"users/{user_id}", {"$select": _USER_FIELDS}))
        except GraphError as exc:
            if exc.status == 404:
                return None
            raise

    def search_users(self, query: str, top: int = 10) -> list[UserSummary]:
        q = sanitize_search(query)
        if len(q) < 2:
            return []
        params = {
            "$search": f'"displayName:{q}" OR "userPrincipalName:{q}" OR "mail:{q}"',
            "$filter": "accountEnabled eq true",
            "$select": _USER_FIELDS,
            "$top": str(min(max(top, 1), 25)),
            "$count": "true",
        }
        return [_user(u) for u in self._get("users", params, advanced=True).get("value", [])]

    def find_address_conflicts(self, address: str, mail_nickname: str) -> list[AddressConflict]:
        raw_a, raw_n = address.lower(), mail_nickname.lower()
        a, n = odata_str(raw_a), odata_str(raw_n)
        conflicts: list[AddressConflict] = []
        user_filter = (
            f"userPrincipalName eq '{a}' or mail eq '{a}' or mailNickname eq '{n}' "
            f"or proxyAddresses/any(p:p eq 'smtp:{a}')"
        )
        for u in self._get_all(
            "users",
            {
                "$filter": user_filter,
                "$select": "id,displayName,userPrincipalName,mail,mailNickname",
                "$count": "true",
            },
            advanced=True,
        ):
            conflicts.append(
                AddressConflict(
                    "usuario", u["id"], u.get("displayName") or "", _which(u, raw_a, raw_n)
                )
            )
        group_filter = (
            f"mail eq '{a}' or mailNickname eq '{n}' or proxyAddresses/any(p:p eq 'smtp:{a}')"
        )
        for g in self._get_all(
            "groups",
            {
                "$filter": group_filter,
                "$select": "id,displayName,mail,mailNickname",
                "$count": "true",
            },
            advanced=True,
        ):
            conflicts.append(
                AddressConflict(
                    "grupo", g["id"], g.get("displayName") or "", _which(g, raw_a, raw_n)
                )
            )
        return conflicts

    def find_users_by_employee_id(self, employee_id: str) -> list[UserSummary]:
        items = self._get_all(
            "users",
            {
                "$filter": f"employeeId eq '{odata_str(employee_id)}'",
                "$select": _USER_FIELDS,
                "$count": "true",
            },
            advanced=True,
        )
        return [_user(u) for u in items]


def _which(obj: dict[str, Any], address: str, nickname: str) -> str:
    if (obj.get("userPrincipalName") or "").lower() == address:
        return "userPrincipalName"
    if (obj.get("mail") or "").lower() == address:
        return "mail"
    if (obj.get("mailNickname") or "").lower() == nickname:
        return "mailNickname"
    return "proxyAddresses"
