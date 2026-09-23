from __future__ import annotations

from typing import Protocol

from app.core.profiles import OnboardingProfile


class StorageBackend(Protocol):
    """Contrato de armazenamento. Cresce nas próximas Sprints."""

    name: str

    def ping(self) -> None:
        """Levanta exceção se o armazenamento não estiver acessível."""

    # Perfis de onboarding
    def list_profiles(self) -> list[OnboardingProfile]: ...
    def get_profile(self, profile_id: str) -> OnboardingProfile | None: ...
    def save_profile(self, profile: OnboardingProfile) -> None: ...
    def delete_profile(self, profile_id: str) -> None: ...
