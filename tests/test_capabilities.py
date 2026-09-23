from __future__ import annotations

from app.core.capabilities import detect_capabilities
from app.graph.models import Organization, SubscribedSku, TapPolicy, TenantSnapshot


def snap(
    plans=("AAD_PREMIUM", "EXCHANGE_S_ENTERPRISE"),
    sync=False,
    tap=TapPolicy(True, 60, 480, False),
    available=True,
):
    return TenantSnapshot(
        organization=Organization("t", "T", sync),
        skus=[SubscribedSku("s", "SPE_E3", "Enabled", 10, 5 if available else 10, tuple(plans))],
        tap_policy=tap,
    )


def test_tenant_completo_sem_alertas():
    c = detect_capabilities(snap())
    assert c.cloud_only and c.entra_p1 and not c.entra_p2 and c.exchange_online and c.tap_enabled
    assert c.license_mode_recommended == "group"
    assert c.lifecycle_engine_recommended == "native"
    assert c.ok and not c.avisos


def test_p2_implica_p1_e_governance_recomenda_lcw():
    c = detect_capabilities(
        snap(plans=("AAD_PREMIUM_P2", "Entra_Identity_Governance", "EXCHANGE_S_STANDARD"))
    )
    assert c.entra_p1 and c.entra_p2 and c.entra_governance
    assert c.lifecycle_engine_recommended == "entra_lcw"


def test_sem_p1_bloqueia_modo_grupo_e_recomenda_direto():
    c = detect_capabilities(snap(plans=("EXCHANGE_S_STANDARD",)), license_mode="group")
    assert not c.ok and c.license_mode_recommended == "direct"
    assert detect_capabilities(snap(plans=("EXCHANGE_S_STANDARD",)), license_mode="direct").ok


def test_sincronizacao_local_bloqueia():
    assert not detect_capabilities(snap(sync=True)).ok


def test_avisos():
    assert any("Temporary Access Pass" in a for a in detect_capabilities(snap(tap=None)).avisos)
    assert any("máximo" in a for a in detect_capabilities(snap(), tap_lifetime_minutes=600).avisos)
    assert any("disponíveis" in a for a in detect_capabilities(snap(available=False)).avisos)
    assert any("Exchange" in a for a in detect_capabilities(snap(plans=("AAD_PREMIUM",))).avisos)
