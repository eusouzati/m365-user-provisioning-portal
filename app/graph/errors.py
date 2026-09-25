from __future__ import annotations


class GraphError(Exception):
    """Falha ao consultar o Microsoft Graph."""

    def __init__(self, message: str, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class GraphPermissionError(GraphError):
    """A identidade do portal não tem a permissão necessária (HTTP 403)."""


class ReadOnlyViolationError(RuntimeError):
    """Tentativa de escrita no Microsoft Graph enquanto o portal está em modo somente leitura."""


def mensagem_usuario(exc: Exception, acao: str = "") -> str:
    """Texto para a tela, sem jargão; o erro original vai para o log.

    ``acao`` completa a frase de permissão (ex.: "gerar o acesso inicial").
    """
    status = getattr(exc, "status", 0) if isinstance(exc, GraphError) else 0
    code = (getattr(exc, "code", "") or "").lower()
    texto = str(exc).lower()
    if status == 403:
        oque = f" para {acao}" if acao else " para esta ação"
        msg = (
            f"O portal não tem permissão{oque} no Microsoft 365. "
            "Peça ao administrador do portal para revisar as permissões."
        )
    elif status == 404:
        msg = "Não encontrado no Microsoft 365 (pode ter sido excluído ou alterado)."
    elif status == 429:
        msg = "O Microsoft 365 pediu uma pausa por excesso de chamadas. Será tentado de novo."
    elif "countviolation" in code or "countviolation" in texto or "licen" in texto:
        msg = "Não há licenças disponíveis no Microsoft 365."
    elif 400 <= status < 500:
        msg = "O Microsoft 365 recusou a alteração."
    elif isinstance(exc, GraphError):
        msg = "O Microsoft 365 não respondeu agora. Será tentado de novo."
    else:
        return str(exc)
    return f"{msg} (código {status})" if status else msg
