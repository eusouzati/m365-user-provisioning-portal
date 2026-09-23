"""Proteção CSRF (double submit cookie + verificação de Origin).

- Um token aleatório fica num cookie HttpOnly/SameSite=Strict.
- Os formulários incluem o mesmo token num campo oculto (``csrf_token``).
- Em POST/PUT/PATCH/DELETE o backend exige que ambos coincidam e que o
  cabeçalho Origin (quando enviado) seja o próprio portal.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import ForbiddenError

COOKIE = "m365up_csrf"
FIELD = "csrf_token"
HEADER = "X-CSRF-Token"


class CsrfCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get(COOKIE)
        is_new = not token or len(token) < 32
        if is_new:
            token = secrets.token_urlsafe(32)
        request.state.csrf_token = token
        response = await call_next(request)
        if is_new:
            response.set_cookie(
                COOKIE,
                token,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
                path="/",
            )
        return response


async def verify_csrf(request: Request) -> None:
    """Dependência para rotas que alteram dados."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise ForbiddenError("csrf")
    cookie = request.cookies.get(COOKIE, "")
    sent = request.headers.get(HEADER, "")
    if not sent:
        form = await request.form()
        sent = str(form.get(FIELD, ""))
    if not cookie or not sent or not secrets.compare_digest(cookie, sent):
        raise ForbiddenError("csrf")
