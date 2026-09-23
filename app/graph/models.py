"""Modelos (somente leitura) do Microsoft Graph usados pelo portal."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Organization:
    id: str
    display_name: str
    on_premises_sync_enabled: bool
    country: str = ""


@dataclass(frozen=True)
class Domain:
    name: str
    is_default: bool
    is_verified: bool


@dataclass(frozen=True)
class SubscribedSku:
    sku_id: str
    sku_part_number: str
    capability_status: str
    enabled_units: int
    consumed_units: int
    service_plans: tuple[str, ...] = ()
    applies_to: str = "User"

    @property
    def available_units(self) -> int:
        return max(self.enabled_units - self.consumed_units, 0)


@dataclass(frozen=True)
class TapPolicy:
    enabled: bool
    default_lifetime_minutes: int
    max_lifetime_minutes: int
    is_usable_once: bool


@dataclass(frozen=True)
class Group:
    id: str
    display_name: str
    description: str = ""
    security_enabled: bool = True
    mail_enabled: bool = False
    is_m365: bool = False
    is_dynamic: bool = False
    is_role_assignable: bool = False
    assigned_license_sku_ids: tuple[str, ...] = ()
    mail: str = ""

    @property
    def is_license_group(self) -> bool:
        return bool(self.assigned_license_sku_ids)


@dataclass(frozen=True)
class UserSummary:
    id: str
    display_name: str
    user_principal_name: str
    mail: str = ""
    job_title: str = ""
    department: str = ""
    account_enabled: bool = True


@dataclass(frozen=True)
class AddressConflict:
    object_type: str  # "usuario" | "grupo"
    object_id: str
    display_name: str
    matched: str  # atributo que colidiu


@dataclass
class TenantSnapshot:
    """Fotografia do tenant usada na página de capacidades."""

    organization: Organization
    domains: list[Domain] = field(default_factory=list)
    skus: list[SubscribedSku] = field(default_factory=list)
    tap_policy: TapPolicy | None = None
    groups: list[Group] = field(default_factory=list)
