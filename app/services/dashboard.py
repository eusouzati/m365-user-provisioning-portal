"""Painel do Administrador (Sprint 9): números do dia a dia, sem dados pessoais extras."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.config import Settings
from app.core.audit import AuditEvent
from app.core.profiles import eligible_skus
from app.core.workflow import FINAL_STATUSES, STATUS_LABELS, ProvisioningRequest
from app.graph.directory import DirectoryCache
from app.services.onboarding import today_in
from app.storage import StorageBackend

JANELA_DIAS = 7


@dataclass
class Dashboard:
    hoje: date
    pendentes: int = 0
    em_andamento: int = 0
    falhas: list[ProvisioningRequest] = field(default_factory=list)
    admissoes: list[ProvisioningRequest] = field(default_factory=list)
    desligamentos: list[ProvisioningRequest] = field(default_factory=list)
    por_status: list[tuple[str, str, int]] = field(default_factory=list)  # (status, rótulo, n)
    licencas: list = field(default_factory=list)
    licencas_erro: str = ""
    ultimo_ciclo: dict | None = None
    recentes: list[AuditEvent] = field(default_factory=list)
    anonimizaveis: int = 0


def build_dashboard(
    storage: StorageBackend, directory: DirectoryCache, settings: Settings
) -> Dashboard:
    from app.services.privacy import eligible

    hoje = today_in(settings)
    fim = hoje + timedelta(days=JANELA_DIAS)
    todas = storage.list_requests(limit=100_000)
    d = Dashboard(hoje=hoje)
    d.pendentes = sum(1 for r in todas if r.status == "enviada")
    d.em_andamento = sum(1 for r in todas if r.status not in FINAL_STATUSES)
    d.falhas = [r for r in todas if r.status == "falha_parcial"]
    d.admissoes = sorted(
        (
            r
            for r in todas
            if not r.eh_desligamento
            and r.status in ("aprovada", "conta_criada", "licenciada")
            and r.data_admissao
            and hoje <= r.data_admissao <= fim
        ),
        key=lambda r: r.data_admissao,
    )
    d.desligamentos = sorted(
        (
            r
            for r in todas
            if r.eh_desligamento
            and r.status in ("enviada", "aprovada")
            and r.data_desligamento
            and r.data_desligamento <= fim
        ),
        key=lambda r: r.data_desligamento,
    )
    contagem = Counter(r.status for r in todas)
    d.por_status = [(s, STATUS_LABELS[s], contagem[s]) for s in STATUS_LABELS if contagem[s]]
    try:
        d.licencas = sorted(
            eligible_skus(directory.skus()), key=lambda s: (s.available_units, s.sku_part_number)
        )
    except Exception:  # Graph fora do ar ou sem token: o painel continua
        d.licencas_erro = "Não foi possível consultar as licenças no Microsoft 365 agora."
    try:
        d.ultimo_ciclo = storage.get_state("ultimo_ciclo")
    except Exception:
        d.ultimo_ciclo = None
    try:
        d.recentes = storage.list_audit(limit=10)
    except Exception:
        d.recentes = []
    d.anonimizaveis = len(eligible(todas, settings))
    return d
