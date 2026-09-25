"""Motor de ciclo de vida nativo (não depende de Entra ID Governance).

Executado de hora em hora pelo agendador (Logic App → POST /interno/ciclo-de-vida) ou
manualmente pelo Administrador. Para cada conta criada:

  D-1 (LICENSE_LEAD_DAYS antes da admissão): atribui a licença
      - LICENSE_MODE=group: adiciona ao grupo de licença do perfil (revalidado no tenant)
      - LICENSE_MODE=direct: atribui o SKU diretamente (verifica unidades disponíveis)
  D0 (data de admissão): ativa a conta (accountEnabled=true)

Também executa os desligamentos aprovados cujo horário de bloqueio chegou (Sprint 8,
ver app/services/offboarding.py) e tenta de novo os que tiveram falha parcial.

Estados: conta_criada → licenciada → ativa (sem licença: conta_criada → ativa).
Idempotente: rodar várias vezes não duplica nada; falhas são tentadas de novo na próxima
execução. A ativação só acontece depois que a licença (quando existir) foi atribuída.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.config import Settings
from app.core.audit import AuditEvent, current_actor
from app.core.profiles import eligible_license_groups, eligible_skus
from app.core.workflow import (
    LIFECYCLE_KEYS,
    Etapa,
    ProvisioningRequest,
    offboarded_ids,
    transition,
)
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError, mensagem_usuario
from app.graph.writer import GraphWriter
from app.services.offboarding import EXECUTABLE as OFFBOARDING_EXECUTABLE
from app.services.offboarding import OffboardingService, is_due
from app.services.onboarding import today_in
from app.services.privacy import run_retention
from app.services.provisioning import ensure_lifecycle_steps
from app.storage import StorageBackend
from app.storage.errors import ConcurrencyError

logger = logging.getLogger("m365up.ciclo")

ELIGIBLE = frozenset({"conta_criada", "licenciada", "falha_parcial"})
MAX_PER_RUN = 100


class LifecycleStepError(RuntimeError):
    pass


@dataclass
class LifecycleReport:
    executado_em: datetime
    dry_run: bool
    analisadas: int = 0
    licenciadas: list[str] = field(default_factory=list)
    ativadas: list[str] = field(default_factory=list)
    desligadas: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    anonimizadas: list[str] = field(default_factory=list)
    ignoradas_concorrencia: list[str] = field(default_factory=list)

    def resumo(self) -> str:
        return (
            f"{self.analisadas} analisada(s), {len(self.licenciadas)} licenciada(s), "
            f"{len(self.ativadas)} ativada(s), {len(self.desligadas)} desligamento(s), "
            f"{len(self.falhas)} falha(s), {len(self.anonimizadas)} anonimizada(s)"
        )

    def as_dict(self) -> dict:
        return {
            "executadoEm": self.executado_em.isoformat(),
            "dryRun": self.dry_run,
            "analisadas": self.analisadas,
            "licenciadas": self.licenciadas,
            "ativadas": self.ativadas,
            "desligadas": self.desligadas,
            "falhas": self.falhas,
            "anonimizadas": self.anonimizadas,
            "ignoradasConcorrencia": self.ignoradas_concorrencia,
        }


def _provisioned(req: ProvisioningRequest) -> bool:
    prov = [e for e in req.etapas if e.chave not in LIFECYCLE_KEYS]
    return bool(req.object_id) and bool(prov) and all(e.status == "ok" for e in prov)


class LifecycleService:
    def __init__(
        self,
        *,
        settings: Settings,
        writer: GraphWriter,
        directory: DirectoryCache,
        storage: StorageBackend,
    ) -> None:
        self.settings = settings
        self.writer = writer
        self.directory = directory
        self.storage = storage

    def run(self, today: date | None = None, now: datetime | None = None) -> LifecycleReport:
        report = LifecycleReport(executado_em=datetime.now(UTC), dry_run=self.writer.dry_run)
        # LGPD: vale também em DRY_RUN (são dados do portal, não do Microsoft 365)
        try:
            report.anonimizadas = run_retention(self.storage, self.settings, now)
        except Exception:  # a retenção nunca impede licença, ativação e desligamentos
            logger.exception("LGPD: falha na retenção; o ciclo de vida continua")
        self._run(report, today or today_in(self.settings), now)
        self._save_state(report)
        return report

    def _save_state(self, report: LifecycleReport) -> None:
        """Última execução (painel) e evento de auditoria quando algo aconteceu."""
        try:
            self.storage.set_state("ultimo_ciclo", report.as_dict())
            if report.analisadas or report.anonimizadas or report.falhas:
                oid, nome = current_actor()
                self.storage.append_audit(
                    AuditEvent(
                        ator_oid=oid,
                        ator_nome=nome,
                        acao="ciclo.executado",
                        detalhe=report.resumo(),
                    )
                )
        except Exception:  # registro auxiliar: nunca derruba o ciclo
            logger.exception("Falha ao registrar a execução do ciclo de vida")

    def _run(self, report: LifecycleReport, hoje: date, now: datetime | None) -> None:
        if self.writer.dry_run:
            logger.info("Ciclo de vida em DRY_RUN: nada será alterado")
            return

        todas = self.storage.list_requests(limit=1000)
        desligados = offboarded_ids(todas)  # nunca ativar/licenciar conta em desligamento
        candidatos = [
            r
            for r in todas
            if not r.eh_desligamento
            and r.status in ELIGIBLE
            and _provisioned(r)
            and r.object_id.lower() not in desligados
        ][:MAX_PER_RUN]
        for req in candidatos:
            report.analisadas += 1
            try:
                self._process(req, hoje, report)
            except ConcurrencyError:
                report.ignoradas_concorrencia.append(req.id)
                self._undo_if_offboarded(req, report)

        agora = now or datetime.now(UTC)
        desligamentos = [
            r
            for r in todas
            if r.eh_desligamento
            and r.status in OFFBOARDING_EXECUTABLE
            and is_due(r, self.settings, agora)
        ][:MAX_PER_RUN]
        offboarding = OffboardingService(
            settings=self.settings,
            writer=self.writer,
            directory=self.directory,
            storage=self.storage,
        )
        for req in desligamentos:
            report.analisadas += 1
            try:
                req = offboarding.run(req)
            except ConcurrencyError:
                report.ignoradas_concorrencia.append(req.id)
                continue
            (report.desligadas if req.status == "desligada" else report.falhas).append(req.id)

        logger.info(
            "Ciclo de vida: %s analisadas, %s licenciadas, %s ativadas, %s desligadas, %s falhas",
            report.analisadas,
            len(report.licenciadas),
            len(report.ativadas),
            len(report.desligadas),
            len(report.falhas),
        )
        return

    # --------------------------------------------------------------------
    def _process(self, req: ProvisioningRequest, hoje: date, report: LifecycleReport) -> None:
        if self._offboarded_now(req.object_id):
            return  # desligamento aprovado depois da leitura inicial: não licencia nem ativa
        ensure_lifecycle_steps(req, self.settings)
        etapas = {e.chave: e for e in req.etapas}
        mudou = False

        lic = etapas.get("licenca")
        if lic and lic.status != "ok" and req.data_licenca and hoje >= req.data_licenca:
            mudou = True
            if self._try(lic, lambda: self._license(req)):
                report.licenciadas.append(req.id)
            else:
                report.falhas.append(req.id)

        ativar = etapas["ativar"]
        licenca_ok = lic is None or lic.status == "ok"
        if ativar.status != "ok" and hoje >= req.data_admissao:
            if not licenca_ok:
                if ativar.detalhe != "Aguardando a atribuição da licença.":
                    ativar.status, ativar.detalhe = (
                        "pendente",
                        "Aguardando a atribuição da licença.",
                    )
                    mudou = True
            else:
                mudou = True
                if self._offboarded_now(req.object_id):
                    return  # desligamento aprovado no meio desta execução: não ativa
                if self._try(ativar, lambda: self.writer.enable_user(req.object_id)):
                    report.ativadas.append(req.id)
                else:
                    report.falhas.append(req.id)

        if not mudou:
            return
        falhou = [e for e in req.etapas if e.chave in LIFECYCLE_KEYS and e.status == "falhou"]
        if falhou:
            transition(req, "falha_parcial", "Falha em: " + "; ".join(e.nome for e in falhou))
        elif ativar.status == "ok":
            transition(req, "ativa", "Conta ativada no dia da admissão.")
        elif lic and lic.status == "ok":
            transition(req, "licenciada", "Licença atribuída (caixa de correio em preparação).")
        else:
            transition(req, "conta_criada", "")
        self.storage.update_request(req)

    def _offboarded_now(self, object_id: str) -> bool:
        """Consulta atual (não a lista lida no início da execução)."""
        return object_id.lower() in offboarded_ids(self.storage.list_requests(limit=1000))

    def _undo_if_offboarded(self, req: ProvisioningRequest, report: LifecycleReport) -> None:
        """Se a conta foi ativada nesta execução mas um desligamento foi aprovado ao mesmo
        tempo (a gravação conflitou), bloqueia de novo: o desligamento sempre prevalece."""
        mexeu = req.id in report.ativadas or req.id in report.licenciadas
        if not mexeu or not self._offboarded_now(req.object_id):
            return
        try:
            if req.id in report.ativadas:
                self.writer.disable_user(req.object_id)
            grupo = req.perfil.grupo_licenca
            if req.id in report.licenciadas and grupo and self.settings.license_mode == "group":
                self.writer.remove_group_member(grupo["id"], req.object_id)
            logger.warning("Ativação/licença de %s desfeita: desligamento simultâneo", req.id)
        except GraphError as exc:
            logger.error("Falha ao desfazer a ativação de %s: %s", req.id, exc)
        for lista in (report.ativadas, report.licenciadas):
            if req.id in lista:
                lista.remove(req.id)

    @staticmethod
    def _try(etapa: Etapa, action) -> bool:
        try:
            action()
        except (GraphError, LifecycleStepError) as exc:
            etapa.status, etapa.detalhe, etapa.em = (
                "falhou",
                mensagem_usuario(exc)[:300],
                datetime.now(UTC),
            )
            logger.warning("Etapa %s falhou: %s", etapa.chave, exc)
            return False
        etapa.status, etapa.detalhe, etapa.em = "ok", "", datetime.now(UTC)
        return True

    def _license(self, req: ProvisioningRequest) -> None:
        if self.settings.license_mode == "group":
            grupo = req.perfil.grupo_licenca
            if not grupo:
                raise LifecycleStepError("O perfil não tem grupo de licença.")
            permitidos = {
                g.id.lower()
                for g in eligible_license_groups(
                    self.directory.groups(refresh=True), self.settings.protected_groups
                )
            }
            if grupo["id"].lower() not in permitidos:
                raise LifecycleStepError(
                    "O grupo de licença não é mais válido (removido, sem licença ou protegido)."
                )
            self.writer.add_group_member(grupo["id"], req.object_id)
            return

        sku = req.perfil.sku_licenca
        if not sku:
            raise LifecycleStepError("O perfil não tem licença.")
        disponivel = next(
            (
                s
                for s in eligible_skus(self.directory.skus(refresh=True))
                if s.sku_id.lower() == sku["sku_id"].lower()
            ),
            None,
        )
        if not disponivel:
            raise LifecycleStepError("A licença do perfil não existe mais no Microsoft 365.")
        if disponivel.available_units <= 0:
            raise LifecycleStepError(
                f"Sem unidades disponíveis de {disponivel.sku_part_number}; será tentado de novo."
            )
        self.writer.assign_license(req.object_id, sku["sku_id"])
