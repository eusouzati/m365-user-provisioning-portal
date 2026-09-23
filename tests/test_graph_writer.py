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
