"""Integração com o Microsoft Graph (somente leitura nesta versão)."""

from __future__ import annotations

from app.config import Settings
from app.graph.errors import GraphError, GraphPermissionError, ReadOnlyViolationError
from app.graph.service import GraphService


def build_graph(settings: Settings) -> GraphService:
    if settings.graph_backend == "fake":
        from app.graph.fake import FakeGraphService

        return FakeGraphService()

    from azure.identity import DefaultAzureCredential

    from app.graph.service import MsGraphService

    # No App Service, AZURE_CLIENT_ID seleciona a Managed Identity atribuída pelo usuário.
    return MsGraphService(DefaultAzureCredential())


__all__ = [
    "GraphError",
    "GraphPermissionError",
    "GraphService",
    "ReadOnlyViolationError",
    "build_graph",
]
