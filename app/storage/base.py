from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from app.core.audit import AuditEvent
from app.core.profiles import OnboardingProfile
from app.core.workflow import ProvisioningRequest


class StorageBackend(Protocol):
    """Contrato de armazenamento. Implementações: SQLite (local) e Azure Table (nuvem)."""

    name: str

    def ping(self) -> None:
        """Levanta exceção se o armazenamento não estiver acessível."""

    # Perfis de onboarding
    def list_profiles(self) -> list[OnboardingProfile]: ...
    def get_profile(self, profile_id: str) -> OnboardingProfile | None: ...
    def save_profile(self, profile: OnboardingProfile) -> None: ...
    def delete_profile(self, profile_id: str) -> None: ...

    # Solicitações
    def next_request_id(self, day: date) -> str:
        """Próximo Request ID do dia (REQ-AAAAMMDD-NNNN), atômico."""

    def create_request(self, req: ProvisioningRequest) -> None:
        """Grava nova solicitação. DuplicateRequestError se a chave de idempotência já existe."""

    def get_request(self, request_id: str) -> ProvisioningRequest | None: ...

    def update_request(self, req: ProvisioningRequest) -> ProvisioningRequest:
        """Grava se ninguém alterou desde a leitura (versão). ConcurrencyError caso contrário."""

    def list_requests(
        self, *, status: str | None = None, solicitante_oid: str | None = None, limit: int = 200
    ) -> list[ProvisioningRequest]:
        """Mais recentes primeiro."""

    # Auditoria (somente acréscimo) e estado (ex.: última execução do agendador)
    def append_audit(self, event: AuditEvent) -> None: ...
    def list_audit(
        self, *, inicio: datetime | None = None, fim: datetime | None = None, limit: int = 500
    ) -> list[AuditEvent]:
        """Mais recentes primeiro."""

    def get_state(self, key: str) -> dict | None: ...
    def set_state(self, key: str, value: dict) -> None: ...
