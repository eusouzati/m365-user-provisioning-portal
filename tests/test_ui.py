"""Layout (Sprint 11): menu lateral, tema, ícones e compatibilidade com a CSP."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import Roles
from app.icons import ICONES, icone
from app.main import create_app
from app.templating import _iniciais
from tests.conftest import make_settings, principal_header

APP = Path(__file__).resolve().parents[1] / "app"
H = "X-MS-CLIENT-PRINCIPAL"


def _cliente(tmp_path, roles) -> tuple[TestClient, dict]:
    s = make_settings(tmp_path, auth_mode="easyauth", website_auth_enabled=True)
    oid = "aaaaaaaa-0000-0000-0000-00000000000a"
    headers = {H: principal_header(oid=oid, name="Ana Souza", roles=roles)}
    return TestClient(create_app(s), follow_redirects=False), headers


def test_menu_lateral_marca_a_pagina_atual(tmp_path):
    c, h = _cliente(tmp_path, (Roles.SOLICITANTE, Roles.APROVADOR, Roles.ADMINISTRADOR))
    html = c.get("/aprovacoes", headers=h).text
    nav = re.search(r'<nav class="lateral".*?</nav>', html, re.S).group(0)
    atual = re.findall(r'<a href="([^"]+)" aria-current="page"', nav)
    assert atual == ["/aprovacoes"]
    for destino in ("/", "/solicitacoes", "/equipe", "/admin/painel"):
        assert f'href="{destino}"' in nav


def test_menu_so_mostra_o_que_o_papel_permite(tmp_path):
    c, h = _cliente(tmp_path, (Roles.SOLICITANTE,))
    nav = re.search(r'<nav class="lateral".*?</nav>', c.get("/", headers=h).text, re.S).group(0)
    assert 'href="/solicitacoes"' in nav
    assert "/aprovacoes" not in nav and "/admin" not in nav


def test_desligamento_destaca_solicitacoes(tmp_path):
    c, h = _cliente(tmp_path, (Roles.SOLICITANTE,))
    html = c.get("/desligamentos/novo", headers=h).text
    assert '<a href="/solicitacoes" aria-current="page"' in html


def test_topo_tem_avatar_tema_e_sair(tmp_path):
    c, h = _cliente(tmp_path, (Roles.SOLICITANTE,))
    html = c.get("/", headers=h).text
    assert ">AS<" in html  # iniciais de Ana Souza
    assert "data-tema-alternar" in html and 'popovertarget="menu-usuario"' in html
    assert "/.auth/logout" in html
    assert "js/tema.js" in html and "js/ui.js" in html


def test_sem_estilo_ou_script_inline_por_causa_da_csp():
    """A CSP é style-src 'self' e script-src 'self': nada inline nos templates."""
    for t in (APP / "templates").glob("*.html"):
        texto = t.read_text(encoding="utf-8")
        assert not re.search(r"\sstyle=", texto), t.name
        assert not re.search(r"<style", texto), t.name
        assert not re.search(r"\son[a-z]+=", texto), t.name  # onclick= etc.
        for m in re.finditer(r"<script([^>]*)>", texto):
            assert "src=" in m.group(1), f"script inline em {t.name}"


def test_css_sem_recursos_externos():
    css = (APP / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "@import" not in css
    for url in re.findall(r"url\(\"?([^\")]+)", css):
        assert url.startswith("data:"), url


@pytest.mark.parametrize("arquivo", ["css/app.css", "js/tema.js", "js/ui.js", "img/icone.svg"])
def test_arquivos_estaticos_servidos(client, arquivo):
    resp = client.get(f"/static/{arquivo}")
    assert resp.status_code == 200 and resp.content


def test_icones_sao_decorativos_e_validos():
    for nome in ICONES:
        svg = str(icone(nome))
        assert svg.startswith("<svg") and 'aria-hidden="true"' in svg
        assert "<script" not in svg and "href" not in svg
    with pytest.raises(KeyError):
        icone("inexistente")


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [("Auto Silva", "AS"), ("maria", "M"), ("João da Silva", "JS"), ("", "?"), ("  ", "?")],
)
def test_iniciais(nome, esperado):
    assert _iniciais(nome) == esperado


# ----------------------------------------------------------- linguagem simples
JARGAO = re.compile(
    r"DRY_RUN|\bUPN\b|Object ID|\btenant\b|Microsoft Graph|\bTAP\b|\bD-1\b|\bD0\b|_DAYS\b"
)


def _sem_detalhes_tecnicos(html: str) -> str:
    """Remove os blocos recolhidos para administradores e os atributos das tags."""
    html = re.sub(r'<details class="tecnico">.*?</details>', "", html, flags=re.S)
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def test_telas_sem_jargao_tecnico(tmp_path):
    c, h = _cliente(tmp_path, (Roles.SOLICITANTE, Roles.APROVADOR, Roles.ADMINISTRADOR))
    for url in (
        "/",
        "/solicitacoes",
        "/solicitacoes/novo",
        "/desligamentos/novo",
        "/aprovacoes",
        "/equipe",
        "/admin",
        "/admin/painel",
        "/admin/privacidade",
        "/privacidade",
    ):
        texto = _sem_detalhes_tecnicos(c.get(url, headers=h).text)
        assert not JARGAO.search(texto), (url, JARGAO.search(texto).group(0))


@pytest.mark.parametrize(
    ("status", "code", "trecho"),
    [
        (403, "Authorization_RequestDenied", "não tem permissão"),
        (404, "Request_ResourceNotFound", "Não encontrado"),
        (429, "TooManyRequests", "pausa"),
        (400, "CountViolation", "licenças disponíveis"),
        (400, "Request_BadRequest", "recusou"),
        (503, "", "não respondeu"),
    ],
)
def test_mensagem_usuario_sem_jargao(status, code, trecho):
    from app.graph.errors import GraphError, mensagem_usuario

    msg = mensagem_usuario(GraphError(f"Graph {status} {code}: detalhe interno", status, code))
    assert trecho in msg and f"(código {status})" in msg
    assert "Graph" not in msg and "detalhe interno" not in msg
    if code:
        assert code not in msg
