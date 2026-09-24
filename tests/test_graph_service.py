from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.graph.errors import GraphError, GraphPermissionError, ReadOnlyViolationError
from app.graph.service import GRAPH_BASE, MsGraphService, odata_str, sanitize_search


class Cred:
    def __init__(self):
        self.calls = 0

    def get_token(self, scope):
        self.calls += 1
        assert scope == "https://graph.microsoft.com/.default"
        return SimpleNamespace(token="tok", expires_on=9_999_999_999)


def make(handler):
    cred = Cred()
    svc = MsGraphService(
        cred, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None
    )
    return svc, cred


def test_paginacao_e_token_em_cache():
    def handler(req: httpx.Request):
        assert req.headers["Authorization"] == "Bearer tok"
        if "skiptoken" in str(req.url):
            return httpx.Response(200, json={"value": [{"id": "d2", "isVerified": True}]})
        return httpx.Response(
            200,
            json={
                "value": [{"id": "d1", "isDefault": True}],
                "@odata.nextLink": f"{GRAPH_BASE}/domains?$skiptoken=x",
            },
        )

    svc, cred = make(handler)
    assert [d.name for d in svc.list_domains()] == ["d1", "d2"]
    svc.list_domains()
    assert cred.calls == 1


def test_nextlink_de_outro_host_rejeitado():
    def handler(req):
        return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://evil.example/x"})

    svc, _ = make(handler)
    with pytest.raises(GraphError):
        svc.list_domains()


def test_retry_em_429_respeita_retry_after():
    calls = []
    sleeps = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"value": []})

    svc = MsGraphService(
        Cred(), httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append
    )
    assert svc.list_domains() == []
    assert sleeps == [3]


def test_403_vira_erro_de_permissao():
    def handler(req):
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": "Authorization_RequestDenied",
                    "message": "Insufficient privileges",
                }
            },
        )

    svc, _ = make(handler)
    with pytest.raises(GraphPermissionError) as exc:
        svc.list_groups()
    assert exc.value.status == 403


def test_escrita_bloqueada():
    svc, _ = make(lambda req: httpx.Response(200, json={}))
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        with pytest.raises(ReadOnlyViolationError):
            svc._request(method, "users")


def test_skus_e_grupos_normalizados():
    def handler(req):
        path = urlsplit(str(req.url)).path
        if path.endswith("subscribedSkus"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "skuId": "s1",
                            "skuPartNumber": "SPE_E3",
                            "capabilityStatus": "Enabled",
                            "prepaidUnits": {"enabled": 25},
                            "consumedUnits": 24,
                            "appliesTo": "User",
                            "servicePlans": [
                                {"servicePlanName": "AAD_PREMIUM", "provisioningStatus": "Success"},
                                {"servicePlanName": "X", "provisioningStatus": "Disabled"},
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "g2",
                        "displayName": "b",
                        "securityEnabled": True,
                        "groupTypes": ["DynamicMembership"],
                    },
                    {
                        "id": "g1",
                        "displayName": "A",
                        "securityEnabled": True,
                        "assignedLicenses": [{"skuId": "s1"}],
                        "isAssignableToRole": True,
                    },
                ]
            },
        )

    svc, _ = make(handler)
    sku = svc.list_subscribed_skus()[0]
    assert (sku.available_units, sku.service_plans) == (1, ("AAD_PREMIUM",))
    g1, g2 = svc.list_groups()
    assert g1.id == "g1" and g1.is_license_group and g1.is_role_assignable
    assert g2.is_dynamic


def test_conflitos_de_endereco_com_escape_e_advanced_query():
    seen = []

    def handler(req):
        q = parse_qs(urlsplit(str(req.url)).query)
        seen.append(
            (urlsplit(str(req.url)).path, q["$filter"][0], req.headers.get("ConsistencyLevel"))
        )
        if urlsplit(str(req.url)).path.endswith("/users"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "u1", "displayName": "Jo", "userPrincipalName": "o'neil@contoso.com"}
                    ]
                },
            )
        return httpx.Response(200, json={"value": []})

    svc, _ = make(handler)
    conflicts = svc.find_address_conflicts("O'Neil@contoso.com", "o'neil")
    assert [(c.object_type, c.matched) for c in conflicts] == [("usuario", "userPrincipalName")]
    users_filter = seen[0][1]
    assert "o''neil@contoso.com" in users_filter
    assert "proxyAddresses/any(p:p eq 'smtp:o''neil@contoso.com')" in users_filter
    assert all(h == "eventual" for _, _, h in seen)


def test_busca_de_usuarios_sanitizada():
    captured = {}

    def handler(req):
        captured.update(parse_qs(urlsplit(str(req.url)).query))
        return httpx.Response(
            200,
            json={"value": [{"id": "u", "displayName": "Ana", "userPrincipalName": "ana@c.com"}]},
        )

    svc, _ = make(handler)
    assert svc.search_users('a"n\\a', top=50)[0].display_name == "Ana"
    assert captured["$search"][0].startswith('"displayName:ana"')
    assert captured["$top"] == ["25"]
    assert svc.search_users("a") == []


def test_get_user_rejeita_id_invalido_e_404():
    def handler(req):
        return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})

    svc, _ = make(handler)
    assert svc.get_user("../organization") is None
    assert svc.get_user("00000000-0000-0000-0000-000000000000") is None


def test_tap_policy():
    def handler(req):
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "state": "enabled",
                    "defaultLifetimeInMinutes": 60,
                    "maximumLifetimeInMinutes": 480,
                    "isUsableOnce": False,
                }
            ),
        )

    svc, _ = make(handler)
    tap = svc.get_tap_policy()
    assert tap.enabled and tap.max_lifetime_minutes == 480 and not tap.is_usable_once


def test_helpers():
    assert odata_str("a'b") == "a''b"
    assert sanitize_search(' "x\\y" ') == "xy"


# ------------------------------------------------------------ Sprint 8
UID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def test_memberships_separa_grupos_e_funcoes():
    def handler(req):
        assert req.url.path == f"/v1.0/users/{UID}/memberOf"
        assert "assignedLicenses" in req.url.params["$select"]  # identifica grupos de licença
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "@odata.type": "#microsoft.graph.group",
                        "id": "g2",
                        "displayName": "b",
                        "securityEnabled": True,
                        "groupTypes": ["DynamicMembership"],
                    },
                    {
                        "@odata.type": "#microsoft.graph.group",
                        "id": "g1",
                        "displayName": "A",
                        "securityEnabled": True,
                    },
                    {"@odata.type": "#microsoft.graph.directoryRole", "id": "r1"},
                    {"@odata.type": "#microsoft.graph.administrativeUnit", "id": "au"},
                ]
            },
        )

    svc, _ = make(handler)
    m = svc.list_memberships(UID)
    assert [g.id for g in m.groups] == ["g1", "g2"] and m.groups[1].is_dynamic
    assert m.directory_roles == 1


def test_license_states_direta_prevalece():
    def handler(req):
        return httpx.Response(
            200,
            json={
                "id": UID,
                "licenseAssignmentStates": [
                    {"skuId": "s1", "assignedByGroup": "g1"},
                    {"skuId": "s1", "assignedByGroup": None},
                    {"skuId": "s2", "assignedByGroup": "g2"},
                ],
            },
        )

    svc, _ = make(handler)
    estados = {s.sku_id: s.by_group for s in svc.list_license_states(UID)}
    assert estados == {"s1": False, "s2": True}


def test_gestor_e_subordinados():
    def handler(req):
        if req.url.path.endswith("/manager"):
            return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})
        return httpx.Response(
            200,
            json={
                "value": [
                    {"@odata.type": "#microsoft.graph.user", "id": "u9", "displayName": "Z"},
                    {"@odata.type": "#microsoft.graph.orgContact", "id": "c1"},
                ]
            },
        )

    svc, _ = make(handler)
    assert svc.get_manager(UID) is None
    assert [u.id for u in svc.list_direct_reports(UID)] == ["u9"]


def test_ids_invalidos_nao_chegam_ao_graph():
    svc, _ = make(lambda req: pytest.fail("não deveria chamar o Graph"))
    assert svc.list_memberships("../users").groups == []
    assert svc.list_license_states("x") == [] and svc.get_manager("x") is None
    assert svc.list_direct_reports("x") == []
