from __future__ import annotations


class ConcurrencyError(RuntimeError):
    """O registro foi alterado por outra pessoa desde a leitura."""


class DuplicateRequestError(RuntimeError):
    """Já existe uma solicitação com a mesma chave de idempotência."""

    def __init__(self, existing_id: str) -> None:
        super().__init__(existing_id)
        self.existing_id = existing_id
