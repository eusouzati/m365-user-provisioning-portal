"""Desligamento de colaboradores (Sprint 8).

Fluxo: o RH escolhe o colaborador e o último dia de trabalho → revisão → aprovação
(segregação de funções, revalidação no tenant) → no horário do bloqueio o agendador executa:

  1. bloquear a conta (accountEnabled=false)
  2. revogar as sessões ativas (revokeSignInSessions)
  3. registrar a data de desligamento (employeeLeaveDateTime)
  4. remover dos grupos em que é membro direto (inclusive grupos de licença)
     e, com LICENSE_MODE=direct, das licenças atribuídas diretamente

O que o portal não pode ou não deve fazer vira "ação manual" (grupos dinâmicos, listas de
distribuição, grupos com funções, licenças diretas no modo grupo, subordinados, funções
administrativas). A conta NUNCA é excluída. Falhas ficam registradas e são tentadas de novo
na próxima execução; nada do que já foi feito é desfeito.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.auth import Principal
from app.config import Settings
from app.core.offboarding import OffboardingForm, classify_group
from app.core.workflow import (
    ETAPA_LABELS,
    FINAL_STATUSES,
    ContaPlanejada,
    Etapa,
    Evento,
    GestorSnapshot,
    PerfilSnapshot,
    ProvisioningRequest,
    transition,
)
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError
from app.graph.models import Group, UserSummary
from app.graph.service import GraphService
from app.graph.writer import GraphWriter
from app.services.onboarding import ReviewError, today_in
from app.storage import StorageBackend
from app.storage.errors import ConcurrencyError

logger = logging.getLogger("m365up.desligamento")

EXECUTABLE = frozenset({"aprovada", "falha_parcial"})
BASE_KEYS = ("bloquear", "revogar_sessoes", "data_saida")


class OffboardingError(RuntimeError):
    """Regra de negócio (mensagem em português)."""


# ----------------------------------------------------------------- horários
def block_at(req: ProvisioningRequest, settings: Settings) -> datetime | None:
    """Momento (UTC) do bloqueio; None = imediatamente após a aprovação."""
    if req.dados.get("imediato") or not req.data_desligamento:
        return None
    local = datetime.combine(
        req.data_desligamento, time(settings.offboarding_block_hour), ZoneInfo(settings.timezone)
    )
    return local.astimezone(UTC)


def is_due(req: ProvisioningRequest, settings: Settings, now: datetime | None = None) -> bool:
    quando = block_at(req, settings)
    return quando is None or (now or datetime.now(UTC)) >= quando


def schedule_text(req: ProvisioningRequest, settings: Settings) -> str:
    quando = block_at(req, settings)
    if quando is None:
        return "Imediatamente após a aprovação."
    local = quando.astimezone(ZoneInfo(settings.timezone))
    return f"Agendada para {local:%d/%m/%Y} às {local:%H:%M}."


def plan_scheduled_steps(req: ProvisioningRequest, settings: Settings) -> None:
    """Etapas visíveis enquanto o desligamento aguarda o horário do bloqueio."""
    if req.etapas:
        return
    texto = schedule_text(req, settings)
    req.etapas = [Etapa(chave=k, nome=ETAPA_LABELS[k], detalhe=texto) for k in BASE_KEYS]
    req.etapas.append(
        Etapa(
            chave="grupos",
            nome=ETAPA_LABELS["grupos"],
            detalhe="A lista de grupos é conferida no momento do bloqueio.",
        )
    )


# ------------------------------------------------------------------ revisão
@dataclass
class OffboardingReview:
    form: OffboardingForm
    user: UserSummary
    gestor: UserSummary | None
    remover: list[Group] = field(default_factory=list)
    manuais: list[tuple[Group, str]] = field(default_factory=list)
    licencas_diretas: list[str] = field(default_factory=list)
    subordinados: list[UserSummary] = field(default_factory=list)
    funcoes_admin: int = 0
    bloqueio_em: datetime | None = None  # horário local; None = imediato
    avisos: list[str] = field(default_factory=list)
    admissoes: list[str] = field(default_factory=list)  # encerradas na aprovação


def _sku_names(directory: DirectoryCache) -> dict[str, str]:
    try:
        return {s.sku_id.lower(): s.sku_part_number for s in directory.skus()}
    except GraphError:
        return {}


def in_flight_for(
    storage: StorageBackend, object_id: str, exclude_id: str | None, exclude_idem: str | None
) -> list[ProvisioningRequest]:
    """Solicitações não finalizadas (admissão ou desligamento) para a mesma conta."""
    oid = object_id.lower()
    return [
        r
        for r in storage.list_requests(limit=1000)
        if r.id != exclude_id
        and not (exclude_idem and r.idempotency_key == exclude_idem)
        and r.status not in FINAL_STATUSES
        and r.object_id
        and r.object_id.lower() == oid
    ]


def close_admissions(storage: StorageBackend, offboarding: ProvisioningRequest, ator) -> list[str]:
    """Encerra admissões em andamento da mesma conta (ex.: contratado que não compareceu),
    para que o agendador nunca ative uma conta em desligamento. Devolve os IDs encerrados."""
    encerradas = []
    for r in in_flight_for(storage, offboarding.object_id, offboarding.id, None):
        if r.eh_desligamento:
            continue
        for _tentativa in range(3):
            if r is None or r.status in FINAL_STATUSES:
                break
            transition(
                r,
                "cancelada",
                f"Admissão encerrada pelo desligamento {offboarding.id}.",
                ator=ator,
            )
            try:
                storage.update_request(r)
                encerradas.append(r.id)
                break
            except ConcurrencyError:  # alterada ao mesmo tempo (ex.: agendador): relê e tenta
                r = storage.get_request(r.id)
        else:
            logger.warning("Não foi possível encerrar a admissão %s agora", r.id)
    return encerradas


def build_offboarding_review(
    form: OffboardingForm,
    *,
    settings: Settings,
    graph: GraphService,
    directory: DirectoryCache,
    storage: StorageBackend,
    principal: Principal,
    exclude_id: str | None = None,
    exclude_idem: str | None = None,
) -> OffboardingReview:
    """Confere o pedido contra o estado ATUAL do tenant. ReviewError com a lista de erros."""
    erros: list[str] = []
    hoje = today_in(settings)
    minimo = hoje - timedelta(days=settings.hire_date_past_days)
    maximo = hoje + timedelta(days=settings.hire_date_future_days)
    if not (minimo <= form.data_desligamento <= maximo):
        erros.append(
            f"Último dia de trabalho deve estar entre {minimo:%d/%m/%Y} e {maximo:%d/%m/%Y}."
        )

    user = graph.get_user(form.colaborador_id)
    if user is None:
        raise ReviewError(erros + ["Colaborador não encontrado no Microsoft 365."])
    if user.id.lower() == principal.object_id.lower():
        erros.append("Você não pode solicitar o próprio desligamento.")
    em_curso = in_flight_for(storage, user.id, exclude_id, exclude_idem)
    for outra in em_curso:
        if outra.eh_desligamento:
            erros.append(
                f"Já existe um desligamento em andamento para este colaborador ({outra.id})."
            )
    if erros:
        raise ReviewError(erros)

    mem = graph.list_memberships(user.id)
    review = OffboardingReview(
        form=form,
        user=user,
        gestor=graph.get_manager(user.id),
        subordinados=graph.list_direct_reports(user.id),
        funcoes_admin=mem.directory_roles,
    )
    for g in mem.groups:
        motivo = classify_group(g)
        if motivo:
            review.manuais.append((g, motivo))
        else:
            review.remover.append(g)
    nomes = _sku_names(directory)
    review.licencas_diretas = [
        nomes.get(s.sku_id.lower(), s.sku_id)
        for s in graph.list_license_states(user.id)
        if not s.by_group
    ]
    if not form.imediato:
        review.bloqueio_em = datetime.combine(
            form.data_desligamento,
            time(settings.offboarding_block_hour),
            ZoneInfo(settings.timezone),
        )

    review.admissoes = [r.id for r in em_curso if not r.eh_desligamento]
    if review.admissoes:
        review.avisos.append(
            "Há admissão em andamento para esta conta ("
            + ", ".join(review.admissoes)
            + "). Ela será encerrada na aprovação e a conta não será ativada."
        )
    if not user.account_enabled:
        review.avisos.append(
            "A conta já está desativada; o desligamento vai concluir a remoção dos acessos."
        )
    if review.funcoes_admin:
        review.avisos.append(
            f"O colaborador tem {review.funcoes_admin} função(ões) administrativa(s) no Entra ID. "
            "O portal não consegue bloquear contas administrativas: remova as funções antes "
            "do desligamento (senão o bloqueio falhará e ficará como pendência)."
        )
    if review.subordinados:
        review.avisos.append(
            f"É gestor de {len(review.subordinados)} pessoa(s): defina um novo gestor para elas."
        )
    if review.licencas_diretas and settings.license_mode == "group":
        review.avisos.append(
            "Há licença atribuída diretamente ("
            + ", ".join(review.licencas_diretas)
            + "): remova-a no Centro de administração do Microsoft 365."
        )
    if review.bloqueio_em and review.bloqueio_em.astimezone(UTC) <= datetime.now(UTC):
        review.avisos.append(
            "O horário do bloqueio já passou: ele será feito logo após a aprovação."
        )
    return review


def new_offboarding_request(
    review: OffboardingReview,
    *,
    settings: Settings,
    storage: StorageBackend,
    principal: Principal,
    idempotency_key: str,
) -> ProvisioningRequest:
    from app.services.requests_flow import pessoa

    u = review.user
    g = review.gestor
    req = ProvisioningRequest(
        id=storage.next_request_id(today_in(settings)),
        idempotency_key=idempotency_key,
        tipo="desligamento",
        solicitante=pessoa(principal),
        dados={
            "colaborador_id": u.id,
            "imediato": review.form.imediato,
            "observacao": review.form.observacao,
            "matricula": u.employee_id,
            "cargo": u.job_title,
            "departamento": u.department,
        },
        conta=ContaPlanejada(
            display_name=u.display_name,
            given_name="",
            surname="",
            user_principal_name=u.user_principal_name,
            mail=u.mail,
            mail_nickname="",
        ),
        perfil=PerfilSnapshot(id="", nome=""),
        gestor=GestorSnapshot(
            id=g.id if g else "",
            nome=g.display_name if g else "",
            upn=g.user_principal_name if g else "",
        ),
        data_desligamento=review.form.data_desligamento,
        object_id=u.id,
    )
    req.historico.append(Evento(em=req.criado_em, ator=req.solicitante, de=None, para="enviada"))
    return req


# ----------------------------------------------------------------- execução
class OffboardingService:
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
        self.graph: GraphService = directory.graph
        self.storage = storage

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _ok(self, e: Etapa, detalhe: str = "") -> None:
        dry = self.writer.dry_run
        e.status = "simulado" if dry else "ok"
        e.detalhe = detalhe or ("Nada foi alterado no Microsoft 365." if dry else "")
        e.em = self._now()

    def _fail(self, e: Etapa, exc: Exception) -> None:
        texto = str(exc)
        if isinstance(exc, GraphError) and exc.status == 403:
            texto += (
                " — confira as permissões (Set-GraphPermissions.ps1 -Nivel desligamento) e se a "
                "conta tem funções administrativas."
            )
        e.status, e.detalhe, e.em = "falhou", texto[:300], self._now()

    def run(self, req: ProvisioningRequest) -> ProvisioningRequest:
        """Executa as etapas pendentes/falhas e grava (controle de versão)."""
        if not req.eh_desligamento or req.status not in EXECUTABLE:
            raise OffboardingError(
                f"A solicitação está '{req.status_label}' e não pode ser executada."
            )
        uid = req.object_id
        dry = self.writer.dry_run
        executado = any(e.status in ("ok", "falhou") for e in req.etapas)
        if dry and executado:
            # Já foi executado de verdade: a simulação não pode apagar o registro real.
            return req
        if not executado:
            # Nada foi feito ainda (agendado ou só simulado): monta as etapas do zero,
            # para que a lista de grupos seja conferida agora.
            req.etapas = [Etapa(chave=k, nome=ETAPA_LABELS[k]) for k in BASE_KEYS]
            req.etapas.append(Etapa(chave="grupos", nome=ETAPA_LABELS["grupos"]))
        if not dry:
            # Reserva a execução ANTES de escrever no Graph: um cancelamento ou outra
            # execução simultânea recebe ConcurrencyError em vez de perder o registro.
            req.execucao_em = req.execucao_em or self._now()
            req = self.storage.update_request(req)

        # 1-3: o bloqueio vem primeiro, independente do resto
        for e in req.etapas:
            if e.chave not in BASE_KEYS or e.status == "ok":
                continue
            try:
                if e.chave == "bloquear":
                    self.writer.disable_user(uid)
                elif e.chave == "revogar_sessoes":
                    self.writer.revoke_sessions(uid)
                elif e.chave == "data_saida":
                    quando = block_at(req, self.settings) or req.execucao_em or self._now()
                    self.writer.set_leave_date(uid, quando.strftime("%Y-%m-%dT%H:%M:%SZ"))
                self._ok(e)
            except GraphError as exc:
                logger.warning("Desligamento %s, etapa %s falhou: %s", req.id, e.chave, exc)
                self._fail(e, exc)

        # 4: grupos e licenças (lista conferida agora)
        self._expand_groups(req)
        for e in req.etapas:
            if e.status in ("ok", "manual") or not e.chave.startswith(("rgrupo:", "rlicenca:")):
                continue
            alvo = e.chave.split(":", 1)[1]
            try:
                if e.chave.startswith("rgrupo:"):
                    removido = self.writer.remove_group_member(alvo, uid)
                    self._ok(e, "" if removido or dry else "Já não era membro.")
                else:
                    self.writer.remove_license(uid, alvo)
                    self._ok(e)
            except GraphError as exc:
                logger.warning("Desligamento %s, etapa %s falhou: %s", req.id, e.chave, exc)
                self._fail(e, exc)

        if not dry:
            falhas = [e for e in req.etapas if e.status in ("falhou", "pendente")]
            manuais = [e for e in req.etapas if e.status == "manual"]
            if falhas:
                transition(req, "falha_parcial", "Falha em: " + "; ".join(e.nome for e in falhas))
            else:
                nota = "Conta bloqueada e acessos removidos. A conta não foi excluída."
                if manuais:
                    nota += f" {len(manuais)} ação(ões) manual(is) pendente(s)."
                transition(req, "desligada", nota)
            logger.info("Desligamento %s executado: %s", req.id, req.status)
        return self.storage.update_request(req)

    def _expand_groups(self, req: ProvisioningRequest) -> None:
        """Troca a etapa 'grupos' pelas remoções concretas (uma vez)."""
        placeholder = next((e for e in req.etapas if e.chave == "grupos"), None)
        if placeholder is None:
            return
        uid = req.object_id
        try:
            mem = self.graph.list_memberships(uid)
            licencas = self.graph.list_license_states(uid)
            subordinados = self.graph.list_direct_reports(uid)
        except GraphError as exc:
            self._fail(placeholder, exc)
            return
        novas: list[Etapa] = []
        for g in mem.groups:
            motivo = classify_group(g)
            nome = f"Remover do grupo {g.display_name}"
            if g.is_license_group:
                nome += " (licença)"
            if motivo:
                novas.append(
                    Etapa(chave=f"manual:grupo:{g.id}", nome=nome, status="manual", detalhe=motivo)
                )
            else:
                novas.append(Etapa(chave=f"rgrupo:{g.id}", nome=nome))
        nomes = _sku_names(self.directory)
        for s in licencas:
            if s.by_group:
                continue  # sai junto com o grupo
            nome = f"Remover a licença {nomes.get(s.sku_id.lower(), s.sku_id)}"
            if self.settings.license_mode == "direct":
                novas.append(Etapa(chave=f"rlicenca:{s.sku_id}", nome=nome))
            else:
                novas.append(
                    Etapa(
                        chave=f"manual:licenca:{s.sku_id}",
                        nome=nome,
                        status="manual",
                        detalhe="Atribuída diretamente: remova no Centro de administração "
                        "(ou use LICENSE_MODE=direct).",
                    )
                )
        if subordinados:
            lista = ", ".join(u.display_name for u in subordinados[:10])
            if len(subordinados) > 10:
                lista += f" e mais {len(subordinados) - 10}"
            novas.append(
                Etapa(
                    chave="manual:subordinados",
                    nome=f"Definir novo gestor para {len(subordinados)} pessoa(s)",
                    status="manual",
                    detalhe=f"{lista}. O portal não altera o gestor de outras pessoas.",
                )
            )
        if mem.directory_roles:
            novas.append(
                Etapa(
                    chave="manual:funcoes",
                    nome=f"Remover {mem.directory_roles} função(ões) administrativa(s)",
                    status="manual",
                    detalhe="Remova em Entra ID → Funções e administradores.",
                )
            )
        if not novas:
            self._ok(placeholder, "Não era membro de nenhum grupo.")
            return
        i = req.etapas.index(placeholder)
        req.etapas[i : i + 1] = novas


def run_offboarding_if_due(
    req: ProvisioningRequest,
    *,
    settings: Settings,
    writer: GraphWriter,
    directory: DirectoryCache,
    storage: StorageBackend,
    force: bool = False,
) -> ProvisioningRequest:
    """Após a aprovação: executa agora se for imediato/vencido; senão só agenda as etapas."""
    if force or is_due(req, settings):
        return OffboardingService(
            settings=settings, writer=writer, directory=directory, storage=storage
        ).run(req)
    plan_scheduled_steps(req, settings)
    return storage.update_request(req)
