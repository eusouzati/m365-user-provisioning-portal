from __future__ import annotations

from typing import Protocol


class StorageBackend(Protocol):
    """Contrato mínimo de armazenamento. Cresce nas próximas Sprints."""

    name: str

    def ping(self) -> None:
        """Levanta exceção se o armazenamento não estiver acessível."""
