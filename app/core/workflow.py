"""Solicitação de provisionamento e sua máquina de estados.

Admissão:     enviada ──► aprovada ──► conta_criada ► licenciada ► ativa
Desligamento: enviada ──► aprovada (agendado) ──► desligada
                 │   └──► rejeitada          qualquer etapa ► falha_parcial
                 └──────► cancelada          (desligamento agendado também pode ser cancelado)

Regras:
- quem solicitou NÃO pode aprovar nem rejeitar a própria solicitação;
- rejeitar exige comentário;
- só a própria pessoa (ou um Administrador) cancela, e só enquanto "enviada";
- toda transição fica no histórico (quem, quando, de → para, comentário).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal[
    "enviada",
    "aprovada",
    "rejeitada",
    "cancelada",
    "conta_criada",
    "licenciada",
    "ativa",
    "falha_parcial",
    "desligada",
]

Tipo = Literal["admissao", "desligamento"]
TIPO_LABELS: dict[str, str] = {"admissao": "Admissão", "desligamento": "Desligamento"}

STATUS_LABELS: dict[str, str] = {
    "enviada": "Aguardando aprovação",
    "aprovada": "Aprovada",
    "rejeitada": "Rejeitada",
    "cancelada": "Cancelada",
    "conta_criada": "Conta criada (desativada)",
    "licenciada": "Licenciada",
    "ativa": "Ativa",
    "falha_parcial": "Falha parcial",
    "desligada": "Desligado",
}

FINAL_STATUSES = frozenset({"rejeitada", "cancelada", "ativa", "desligada"})
# Desligamento aprovado (ou concluído): a conta não pode ser ativada nem receber TAP
OFFBOARDING_BLOCKING = frozenset({"aprovada", "falha_parcial", "desligada"})

REQUEST_ID_RE = re.compile(r"^REQ-\d{8}-\d{4,}$")
COMMENT_MIN, COMMENT_MAX = 5, 500


class WorkflowError(ValueError):
    """Transição não permitida (mensagem já em português, para o usuário)."""


class Pessoa(BaseModel):
    oid: str
    nome: str


class Evento(BaseModel):
    em: datetime
    ator: Pessoa
    de: Status | None
    para: Status
    comentario: str = ""


class ContaPlanejada(BaseModel):
    display_name: str
    given_name: str
    surname: str
    user_principal_name: str
    mail: str
    mail_nickname: str


class PerfilSnapshot(BaseModel):
    id: str
    nome: str
    grupos_acesso: list[dict] = Field(default_factory=list)  # [{id, nome}]
    grupo_licenca: dict | None = None
    sku_licenca: dict | None = None


class GestorSnapshot(BaseModel):
    id: str
    nome: str
    upn: str


EtapaStatus = Literal["pendente", "ok", "falhou", "simulado", "manual"]

ETAPA_LABELS: dict[str, str] = {
    "criar_usuario": "Criar usuário (desativado, sem licença)",
    "definir_gestor": "Definir gestor",
    "licenca": "Atribuir licença (D-1)",
    "ativar": "Ativar a conta (D0)",
    # Desligamento (Sprint 8)
    "bloquear": "Bloquear a conta",
    "revogar_sessoes": "Revogar as sessões ativas",
    "data_saida": "Registrar a data de desligamento",
    "grupos": "Remover dos grupos e licenças",
}

# Etapas executadas pelo motor de ciclo de vida (não pelo provisionamento inicial)
LIFECYCLE_KEYS = frozenset({"licenca", "ativar"})

ETAPA_STATUS_LABELS: dict[str, str] = {
    "pendente": "Pendente",
    "ok": "Concluída",
    "falhou": "Falhou",
    "simulado": "Simulada (DRY_RUN)",
    "manual": "Ação manual",
}


class Etapa(BaseModel):
    # criar_usuario | definir_gestor | grupo:<id> | licenca | ativar
    # desligamento: bloquear | revogar_sessoes | data_saida | grupos | rgrupo:<id>
    #               | rlicenca:<sku> | manual:<motivo>
    chave: str
    nome: str
    status: EtapaStatus = "pendente"
    detalhe: str = ""
    em: datetime | None = None


SISTEMA = Pessoa(oid="sistema", nome="Portal (automático)")
ANON = "[anonimizado]"
ANON_NOTE = "Dados pessoais anonimizados"


class ProvisioningRequest(BaseModel):
    id: str
    idempotency_key: str
    tipo: Tipo = "admissao"
    status: Status = "enviada"
    criado_em: datetime = Field(default_factory=lambda: datetime.now(UTC))
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(UTC))
    solicitante: Pessoa
    dados: dict  # campos do formulário (NewHireForm), já validados
    conta: ContaPlanejada
    perfil: PerfilSnapshot
    gestor: GestorSnapshot
    data_admissao: date | None = None
    data_licenca: date | None = None
    data_desligamento: date | None = None  # último dia de trabalho
    historico: list[Evento] = Field(default_factory=list)
    etapas: list[Etapa] = Field(default_factory=list)
    object_id: str = ""  # ID do usuário no Entra (criado na admissão; alvo no desligamento)
    execucao_em: datetime | None = None  # desligamento: início da execução (trava o cancelamento)
    anonimizado_em: datetime | None = None  # LGPD: dados pessoais removidos
    versao: int = 1

    @property
    def status_label(self) -> str:
        if self.eh_desligamento and self.status == "aprovada":
            return "Desligamento agendado"
        return STATUS_LABELS[self.status]

    @property
    def eh_desligamento(self) -> bool:
        return self.tipo == "desligamento"

    @property
    def tipo_label(self) -> str:
        return TIPO_LABELS[self.tipo]

    @property
    def data_efetiva(self) -> date | None:
        """Admissão ou último dia de trabalho, conforme o tipo."""
        return self.data_desligamento if self.eh_desligamento else self.data_admissao

    @property
    def desligamento_iniciado(self) -> bool:
        """A execução do desligamento já começou no Microsoft 365."""
        if self.execucao_em is not None:
            return True
        return any(e.status in ("ok", "falhou") for e in self.etapas)

    def eh_alvo(self, oid: str) -> bool:
        """A pessoa é o próprio colaborador que está sendo desligado."""
        if not (self.eh_desligamento and self.object_id):
            return False
        return self.object_id.lower() == oid.lower()

    @property
    def pendente(self) -> bool:
        return self.status == "enviada"

    def eh_do_solicitante(self, oid: str) -> bool:
        return self.solicitante.oid.lower() == oid.lower()


def transition(
    req: ProvisioningRequest, para: Status, comentario: str = "", ator: Pessoa = SISTEMA
) -> ProvisioningRequest:
    """Transição automática (provisionamento)."""
    if req.status == para:
        return req
    return _transition(req, ator, para, comentario)


def note(req: ProvisioningRequest, ator: Pessoa, comentario: str) -> ProvisioningRequest:
    """Registra um evento no histórico sem mudar o status (ex.: TAP gerado)."""
    agora = datetime.now(UTC)
    req.historico.append(
        Evento(em=agora, ator=ator, de=req.status, para=req.status, comentario=comentario)
    )
    req.atualizado_em = agora
    return req


def offboarded_ids(requests) -> frozenset[str]:
    """Object IDs com desligamento aprovado ou concluído."""
    return frozenset(
        r.object_id.lower()
        for r in requests
        if r.eh_desligamento and r.object_id and r.status in OFFBOARDING_BLOCKING
    )


def _not_target(req: ProvisioningRequest, ator: Pessoa) -> None:
    if req.eh_alvo(ator.oid):
        raise WorkflowError("Você não pode decidir sobre o seu próprio desligamento.")


def format_request_id(day: date, sequence: int) -> str:
    return f"REQ-{day:%Y%m%d}-{sequence:04d}"


def _transition(req: ProvisioningRequest, ator: Pessoa, para: Status, comentario: str = ""):
    agora = datetime.now(UTC)
    req.historico.append(
        Evento(em=agora, ator=ator, de=req.status, para=para, comentario=comentario)
    )
    req.status = para
    req.atualizado_em = agora
    return req


def _clean_comment(comentario: str) -> str:
    return " ".join((comentario or "").split())[:COMMENT_MAX]


def approve(
    req: ProvisioningRequest, aprovador: Pessoa, comentario: str = ""
) -> ProvisioningRequest:
    if req.status != "enviada":
        raise WorkflowError(f"A solicitação está '{req.status_label}' e não pode ser aprovada.")
    if req.eh_do_solicitante(aprovador.oid):
        raise WorkflowError("Você não pode aprovar uma solicitação feita por você.")
    _not_target(req, aprovador)
    return _transition(req, aprovador, "aprovada", _clean_comment(comentario))


def reject(req: ProvisioningRequest, aprovador: Pessoa, comentario: str) -> ProvisioningRequest:
    if req.status != "enviada":
        raise WorkflowError(f"A solicitação está '{req.status_label}' e não pode ser rejeitada.")
    if req.eh_do_solicitante(aprovador.oid):
        raise WorkflowError("Você não pode rejeitar uma solicitação feita por você.")
    _not_target(req, aprovador)
    texto = _clean_comment(comentario)
    if len(texto) < COMMENT_MIN:
        raise WorkflowError(f"Informe o motivo da rejeição (mínimo de {COMMENT_MIN} caracteres).")
    return _transition(req, aprovador, "rejeitada", texto)


def can_cancel(req: ProvisioningRequest) -> bool:
    """Enviada; ou desligamento aprovado que ainda não começou a ser executado."""
    if req.status == "enviada":
        return True
    return req.eh_desligamento and req.status == "aprovada" and not req.desligamento_iniciado


def cancel(
    req: ProvisioningRequest, ator: Pessoa, *, is_admin: bool = False, comentario: str = ""
) -> ProvisioningRequest:
    if not can_cancel(req):
        raise WorkflowError(f"A solicitação está '{req.status_label}' e não pode ser cancelada.")
    _not_target(req, ator)
    if not (is_admin or req.eh_do_solicitante(ator.oid)):
        raise WorkflowError("Somente quem fez a solicitação (ou um administrador) pode cancelá-la.")
    return _transition(req, ator, "cancelada", _clean_comment(comentario))
