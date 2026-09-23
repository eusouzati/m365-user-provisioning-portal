"""Tratamento de erros de autenticação/autorização (HTML para páginas, JSON para a API)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.auth import ForbiddenError, NotAuthenticatedError
from app.templating import templates

MENSAGENS_403 = {
    "sem_papel": "Você está autenticado, mas não possui o papel necessário para esta página.",
    "tenant_nao_autorizado": "Sua conta pertence a outra organização e não pode usar este portal.",
    "audiencia_invalida": "O token de acesso não foi emitido para este portal.",
    "provedor_nao_permitido": "Somente contas Microsoft Entra ID são aceitas.",
}


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotAuthenticatedError)
    async def _not_authenticated(request: Request, exc: NotAuthenticatedError) -> Response:
        settings = request.app.state.settings
        if _is_api(request):
            return JSONResponse(status_code=401, content={"erro": "nao_autenticado"})
        if settings.auth_mode == "easyauth" and settings.website_auth_enabled:
            destino = quote(request.url.path, safe="/")
            return RedirectResponse(
                f"/.auth/login/aad?post_login_redirect_uri={destino}", status_code=302
            )
        return templates.TemplateResponse(
            request,
            "erro.html",
            {
                "settings": settings,
                "principal": None,
                "titulo": "Autenticação necessária",
                "mensagem": "Faça login com sua conta corporativa para continuar.",
            },
            status_code=401,
        )

    @app.exception_handler(ForbiddenError)
    async def _forbidden(request: Request, exc: ForbiddenError) -> Response:
        if _is_api(request):
            return JSONResponse(status_code=403, content={"erro": exc.reason})
        return templates.TemplateResponse(
            request,
            "erro.html",
            {
                "settings": request.app.state.settings,
                "principal": getattr(request.state, "principal", None),
                "titulo": "Acesso negado",
                "mensagem": MENSAGENS_403.get(exc.reason, MENSAGENS_403["sem_papel"]),
            },
            status_code=403,
        )
