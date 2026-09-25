"""Detecção das capacidades do tenant a partir de uma fotografia do Microsoft Graph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.graph.models import TenantSnapshot

_GOVERNANCE = re.compile(r"GOVERNANCE", re.IGNORECASE)


@dataclass
class TenantCapabilities:
    cloud_only: bool
    entra_p1: bool
    entra_p2: bool
    entra_governance: bool
    exchange_online: bool
    tap_enabled: bool
    tap_usable_once_default: bool
    tap_max_minutes: int
    license_mode_recommended: str
    lifecycle_engine_recommended: str
    bloqueios: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.bloqueios


def detect_capabilities(
    snapshot: TenantSnapshot,
    *,
    license_mode: str = "group",
    tap_lifetime_minutes: int = 480,
) -> TenantCapabilities:
    plans = {p for s in snapshot.skus if s.capability_status == "Enabled" for p in s.service_plans}
    p2 = "AAD_PREMIUM_P2" in plans
    p1 = p2 or "AAD_PREMIUM" in plans
    governance = any(_GOVERNANCE.search(p) for p in plans)
    exchange = any(p.startswith("EXCHANGE_S_") for p in plans)
    tap = snapshot.tap_policy

    caps = TenantCapabilities(
        cloud_only=not snapshot.organization.on_premises_sync_enabled,
        entra_p1=p1,
        entra_p2=p2,
        entra_governance=governance,
        exchange_online=exchange,
        tap_enabled=bool(tap and tap.enabled),
        tap_usable_once_default=bool(tap and tap.is_usable_once),
        tap_max_minutes=tap.max_lifetime_minutes if tap else 0,
        license_mode_recommended="group" if p1 else "direct",
        lifecycle_engine_recommended="entra_lcw" if governance else "native",
    )

    if not caps.cloud_only:
        caps.bloqueios.append(
            "A organização sincroniza usuários de um Active Directory local. Este portal cria "
            "contas somente na nuvem; nesse cenário, os usuários devem ser criados no AD local."
        )
    if license_mode == "group" and not p1:
        caps.bloqueios.append(
            "O portal está configurado para dar licenças por grupo, o que exige Microsoft Entra "
            "ID P1. Adquira o P1 ou configure o portal para atribuir licenças diretamente "
            "(veja a documentação de implantação)."
        )
    if not caps.tap_enabled:
        caps.avisos.append(
            "O acesso inicial por código temporário está desativado no Microsoft 365. Sem ele, o "
            "gestor não consegue gerar o primeiro acesso do colaborador (habilite em Entra → "
            "Métodos de autenticação → Temporary Access Pass)."
        )
    elif caps.tap_max_minutes and tap_lifetime_minutes > caps.tap_max_minutes:
        caps.avisos.append(
            f"A validade configurada para o código de acesso ({tap_lifetime_minutes} min) é maior "
            f"que o máximo permitido no Microsoft 365 ({caps.tap_max_minutes} min); será usado o "
            "máximo permitido."
        )
    user_skus = [
        s for s in snapshot.skus if s.applies_to == "User" and s.capability_status == "Enabled"
    ]
    if not any(s.available_units > 0 for s in user_skus):
        caps.avisos.append("Nenhuma licença de usuário com unidades disponíveis.")
    if not exchange:
        caps.avisos.append(
            "Nenhuma licença com Exchange Online: novos usuários não terão caixa de correio."
        )
    return caps
