from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.graph.errors import GraphError
from app.graph.writer import MsGraphWriter


class Cred:
    def get_token(self, scope):
        return SimpleNamespace(token="tok", expires_on=9_999_999_999)


def make(handler, sleeps=None):
    return MsGraphWriter(
        Cred(),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def test_create_user_post():
    seen = {}

    def handler(req):
        seen["method"], seen["path"] = req.method, req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"id": "abc"})

    w = make(handler)
    assert w.create_user({"userPrincipalName": "a@c.com", "accountEnabled": False}) == "abc"
    assert seen["method"] == "POST" and seen["path"] == "/v1.0/users"
    assert seen["body"]["accountEnabled"] is False


def test_post_nao_repete_em_erro_5xx():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503, json={"error": {"code": "ServiceUnavailable"}})

    with pytest.raises(GraphError):
        make(handler).create_user({"userPrincipalName": "a@c.com"})
    assert len(calls) == 1  # escrita ambígua: não repetir às cegas


def test_post_repete_em_429():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(201, json={"id": "x"})

    assert make(handler, sleeps).create_user({"userPrincipalName": "a@c.com"}) == "x"
    assert sleeps == [2]


def test_set_manager_put_ref():
    seen = {}

    def handler(req):
        seen["method"], seen["path"] = req.method, req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(204)

    make(handler).set_manager("u1", "m1")
    assert seen["method"] == "PUT" and seen["path"] == "/v1.0/users/u1/manager/$ref"
    assert seen["body"]["@odata.id"].endswith("/users/m1")


def test_add_group_member_tolera_ja_membro():
    def handler(req):
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "Request_BadRequest",
                    "message": "One or more added object references already exist "
                    "for the following modified properties: 'members'.",
                }
            },
        )

    assert make(handler).add_group_member("g1", "u1") is False


def test_add_group_member_ok_e_erro():
    ok = make(lambda req: httpx.Response(204))
    assert ok.add_group_member("g1", "u1") is True
    denied = make(lambda req: httpx.Response(403, json={"error": {"code": "Denied"}}))
    with pytest.raises(GraphError):
        denied.add_group_member("g1", "u1")


def test_get_user_by_upn_404():
    w = make(lambda req: httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}}))
    assert w.get_user_by_upn("x@c.com") is None


def test_enable_user_patch():
    seen = {}

    def handler(req):
        seen.update(method=req.method, path=req.url.path, body=json.loads(req.content))
        return httpx.Response(204)

    make(handler).enable_user("u1")
    assert seen == {"method": "PATCH", "path": "/v1.0/users/u1", "body": {"accountEnabled": True}}


def test_assign_license():
    seen = {}

    def handler(req):
        seen.update(path=req.url.path, body=json.loads(req.content))
        return httpx.Response(200, json={"id": "u1"})

    make(handler).assign_license("u1", "sku-1")
    assert seen["path"] == "/v1.0/users/u1/assignLicense"
    assert seen["body"]["addLicenses"][0]["skuId"] == "sku-1"
    assert seen["body"]["removeLicenses"] == []


def test_tap_remove_anterior_e_cria_uso_unico():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "GET":
            return httpx.Response(200, json={"value": [{"id": "old"}]})
        if req.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(req.content)
        assert body == {"lifetimeInMinutes": 240, "isUsableOnce": True}
        return httpx.Response(201, json={"id": "new", "temporaryAccessPass": "ABC#123"})

    code = make(handler).create_temporary_access_pass("u1", 240)
    base = "/v1.0/users/u1/authentication/temporaryAccessPassMethods"
    assert code == "ABC#123"
    assert calls == [("GET", base), ("DELETE", f"{base}/old"), ("POST", base)]


def test_tap_nao_aparece_no_log(caplog):
    import logging

    caplog.set_level(logging.DEBUG)

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"value": []})
        return httpx.Response(201, json={"id": "n", "temporaryAccessPass": "SEGREDO-TAP-999"})

    make(handler).create_temporary_access_pass("u1", 60)
    assert "SEGREDO-TAP-999" not in caplog.text


# ------------------------------------------------------------ Sprint 8
def _seen(handler_status=204, body=None):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(handler_status, json=body) if body else httpx.Response(handler_status)

    return seen, handler


def test_disable_revoke_e_data_de_saida():
    seen, handler = _seen()
    w = make(handler)
    w.disable_user("u1")
    w.revoke_sessions("u1")
    w.set_leave_date("u1", "2026-10-09T21:00:00Z")
    assert seen == [
        ("PATCH", "/v1.0/users/u1", {"accountEnabled": False}),
        ("POST", "/v1.0/users/u1/revokeSignInSessions", None),
        ("PATCH", "/v1.0/users/u1", {"employeeLeaveDateTime": "2026-10-09T21:00:00Z"}),
    ]


def test_remove_group_member_delete_ref_e_404_tolerado():
    seen, handler = _seen()
    assert make(handler).remove_group_member("g1", "u1") is True
    assert seen == [("DELETE", "/v1.0/groups/g1/members/u1/$ref", None)]
    gone = make(lambda req: httpx.Response(404, json={"error": {"code": "NotFound"}}))
    assert gone.remove_group_member("g1", "u1") is False


def test_remove_license():
    seen, handler = _seen(200, {"id": "u1"})
    make(handler).remove_license("u1", "sku-1")
    assert seen == [
        ("POST", "/v1.0/users/u1/assignLicense", {"addLicenses": [], "removeLicenses": ["sku-1"]})
    ]


def test_revoke_nao_repete_em_5xx():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500, json={"error": {"code": "InternalServerError"}})

    with pytest.raises(GraphError):
        make(handler).revoke_sessions("u1")
    assert len(calls) == 1
