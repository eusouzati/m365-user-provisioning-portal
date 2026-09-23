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
