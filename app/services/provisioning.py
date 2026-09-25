"""UserProvisioningService — cria no Microsoft Entra ID a conta de uma solicitação aprovada.

Etapas (cada uma registrada individualmente na solicitação):
  1. criar usuário DESATIVADO e SEM licença, com senha aleatória descartada;
  2. definir o gestor;
  3. adicionar aos grupos de acesso do perfil (revalidados agora contra o tenant).
A licença (D-1) e a ativação (D0) ficam para a Sprint 7.

Regras:
- DRY_RUN=true: nenhuma escrita no Graph; as etapas ficam como "simulado".
- Idempotente: reprocessar executa apenas etapas pendentes/falhas; se o usuário já
  existir com a mesma matrícula (tentativa anterior), ele é reaproveitado.
- Falhas parciais nunca desfazem o que já foi feito (o usuário nunca é excluído).
- PROVISIONING_DAILY_LIMIT limita quantas contas podem ser criadas por dia.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.config import Settings
from app.core.passwords import generate_password
from app.core.profiles import TIPOS_COLABORADOR, eligible_access_groups
from app.core.workflow import (
    ETAPA_LABELS,
    LIFECYCLE_KEYS,
    Etapa,
    ProvisioningRequest,
    transition,
)
from app.graph.directory import DirectoryCache
from app.graph.errors import GraphError, mensagem_usuario
from app.graph.writer import GraphWriter
from app.services.onboarding import today_in
from app.storage import StorageBackend

logger = logging.getLogger("m365up.provisionamento")

PROVISIONABLE = frozenset({"aprovada", "falha_parcial"})


class ProvisioningError(RuntimeError):
    """Falha de regra de negócio numa etapa (mensagem em português)."""


def _agora() -> datetime:
    return datetime.now(UTC)


def hire_datetime(req: ProvisioningRequest, settings: Settings) -> str:
    """Meia-noite local da admissão, convertida para UTC (formato do Graph)."""
    local = datetime.combine(req.data_admissao, time(0, 0), ZoneInfo(settings.timezone))
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def user_body(req: ProvisioningRequest, settings: Settings, password: str) -> dict:
    d = req.dados
    body = {
        "accountEnabled": False,
        "displayName": req.conta.display_name,
        "givenName": req.conta.given_name,
        "surname": req.conta.surname,
        "mailNickname": req.conta.mail_nickname,
        "userPrincipalName": req.conta.user_principal_name,
        "usageLocation": settings.m365_default_usage_location,
        "employeeId": d.get("matricula"),
        "employeeType": TIPOS_COLABORADOR.get(d.get("tipo_colaborador", ""), ""),
        "employeeHireDate": hire_datetime(req, settings),
        "jobTitle": d.get("cargo"),
        "department": d.get("departamento"),
        "companyName": d.get("empresa"),
        "officeLocation": d.get("unidade"),
        "city": d.get("cidade"),
        "state": d.get("estado"),
        "country": d.get("pais"),
        "passwordProfile": {"forceChangePasswordNextSignIn": True, "password": password},
    }
    return {k: v for k, v in body.items() if v not in (None, "")}


def plan_steps(req: ProvisioningRequest) -> list[Etapa]:
    etapas = [
        Etapa(chave="criar_usuario", nome=ETAPA_LABELS["criar_usuario"]),
        Etapa(chave="definir_gestor", nome=f"{ETAPA_LABELS['definir_gestor']}: {req.gestor.nome}"),
    ]
    for g in req.perfil.grupos_acesso:
        etapas.append(Etapa(chave=f"grupo:{g['id']}", nome=f"Adicionar ao grupo {g['nome']}"))
    return etapas


def ensure_lifecycle_steps(req: ProvisioningRequest, settings: Settings) -> None:
    """Acrescenta (uma vez) as etapas agendadas de licença (D-1) e ativação (D0)."""
    chaves = {e.chave for e in req.etapas}
    if req.data_licenca and "licenca" not in chaves:
        lic = req.perfil.grupo_licenca or req.perfil.sku_licenca or {}
        nome = lic.get("nome") or lic.get("part_number") or "licença"
        req.etapas.append(
            Etapa(
                chave="licenca",
                nome=f"{ETAPA_LABELS['licenca']}: {nome}",
                detalhe=f"Agendada para {req.data_licenca:%d/%m/%Y}.",
            )
        )
    if "ativar" not in chaves:
        req.etapas.append(
            Etapa(
                chave="ativar",
                nome=ETAPA_LABELS["ativar"],
                detalhe=f"Agendada para {req.data_admissao:%d/%m/%Y}.",
            )
        )


def created_today(storage: StorageBackend, settings: Settings) -> int:
    hoje = today_in(settings)
    tz = ZoneInfo(settings.timezone)
    return sum(
        1
        for r in storage.list_requests(limit=1000)
        for e in r.etapas
        if e.chave == "criar_usuario"
        and e.status == "ok"
        and e.em
        and e.em.astimezone(tz).date() == hoje
    )


class UserProvisioningService:
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

    # ------------------------------------------------------------- utilidades
    def _ok(self, e: Etapa, detalhe: str = "") -> None:
        dry = self.writer.dry_run
        e.status = "simulado" if dry else "ok"
        e.detalhe = detalhe or ("Nada foi alterado no Microsoft 365." if dry else "")
        e.em = _agora()

    @staticmethod
    def _fail(e: Etapa, detalhe: str) -> None:
        e.status, e.detalhe, e.em = "falhou", detalhe[:300], _agora()

    # --------------------------------------------------------------- execução
    def run(self, req: ProvisioningRequest) -> ProvisioningRequest:
        """Executa as etapas ainda não concluídas e grava o resultado (controle de versão)."""
        if req.status not in PROVISIONABLE:
            raise ProvisioningError(
                f"A solicitação está '{req.status_label}' e não pode ser provisionada."
            )
        dry = self.writer.dry_run
        prov = [e for e in req.etapas if e.chave not in LIFECYCLE_KEYS]
        if dry or not prov or all(e.status == "simulado" for e in prov):
            req.etapas = plan_steps(req)
        ensure_lifecycle_steps(req, self.settings)

        user_id = req.object_id
        for etapa in req.etapas:
            if etapa.status == "ok" or etapa.chave in LIFECYCLE_KEYS:
                continue
            try:
                if etapa.chave == "criar_usuario":
                    user_id = self._create_user(req, etapa)
                elif not user_id and not dry:
                    etapa.status, etapa.detalhe = "pendente", "Aguardando a criação do usuário."
                elif etapa.chave == "definir_gestor":
                    self.writer.set_manager(user_id, req.gestor.id)
                    self._ok(etapa)
                elif etapa.chave.startswith("grupo:"):
                    self._add_group(etapa, etapa.chave.split(":", 1)[1], user_id)
            except (GraphError, ProvisioningError) as exc:
                logger.warning("Solicitação %s, etapa %s falhou: %s", req.id, etapa.chave, exc)
                self._fail(etapa, mensagem_usuario(exc))

        if not dry:
            req.object_id = user_id or ""
            pendentes = [
                e
                for e in req.etapas
                if e.chave not in LIFECYCLE_KEYS and e.status in ("falhou", "pendente")
            ]
            if pendentes:
                transition(
                    req, "falha_parcial", "Falha em: " + "; ".join(e.nome for e in pendentes)
                )
            else:
                transition(req, "conta_criada", f"Usuário criado desativado ({req.object_id}).")
        return self.storage.update_request(req)

    def _create_user(self, req: ProvisioningRequest, etapa: Etapa) -> str:
        if self.writer.dry_run:
            self.writer.create_user(user_body(req, self.settings, "(não gerada em DRY_RUN)"))
            self._ok(etapa)
            return ""

        upn = req.conta.user_principal_name
        existente = self.writer.get_user_by_upn(upn)
        if existente:
            if str(existente.get("employeeId") or "") == str(req.dados.get("matricula")):
                self._ok(etapa, "Usuário já existia (tentativa anterior) e foi reaproveitado.")
                return existente["id"]
            raise ProvisioningError(
                f"O login {upn} foi ocupado por outro usuário. Cancele e refaça a solicitação."
            )

        limite = self.settings.provisioning_daily_limit
        if created_today(self.storage, self.settings) >= limite:
            raise ProvisioningError(
                f"Limite diário de {limite} contas criadas atingido. Tente de novo amanhã."
            )

        password = generate_password()
        try:
            user_id = self.writer.create_user(user_body(req, self.settings, password))
        finally:
            del password  # descartada: nunca exibida, registrada ou armazenada
        self._ok(etapa, "Conta criada.")
        logger.info("Solicitação %s: usuário %s criado (desativado)", req.id, user_id)
        return user_id

    def _add_group(self, etapa: Etapa, group_id: str, user_id: str) -> None:
        # Revalida no tenant: o grupo pode ter mudado desde a configuração do perfil.
        permitidos = {
            g.id.lower()
            for g in eligible_access_groups(
                self.directory.groups(refresh=True), self.settings.protected_groups
            )
        }
        if group_id.lower() not in permitidos:
            raise ProvisioningError(
                "Grupo não é mais permitido (removido, protegido, dinâmico ou com funções)."
            )
        added = self.writer.add_group_member(group_id, user_id)
        self._ok(etapa, "" if added or self.writer.dry_run else "Já era membro.")
