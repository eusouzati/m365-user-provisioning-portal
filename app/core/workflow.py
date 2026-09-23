"""Solicitação de provisionamento e sua máquina de estados.

    enviada ──► aprovada ──► (Sprint 6+) conta_criada ► licenciada ► ativa
       │   └──► rejeitada          qualquer etapa ► falha_parcial
       └──────► cancelada

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
]

STATUS_LABELS: dict[str, str] = {
    "enviada": "Aguardando aprovação",
    "aprovada": "Aprovada",
    "rejeitada": "Rejeitada",
    "cancelada": "Cancelada",
    "conta_criada": "Conta criada",
    "licenciada": "Licenciada",
    "ativa": "Ativa",
    "falha_parcial": "Falha parcial",
}

FINAL_STATUSES = frozenset({"rejeitada", "cancelada", "ativa"})

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


class ProvisioningRequest(BaseModel):
    id: str
    idempotency_key: str
    status: Status = "enviada"
    criado_em: datetime = Field(default_factory=lambda: datetime.now(UTC))
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(UTC))
    solicitante: Pessoa
    dados: dict  # campos do formulário (NewHireForm), já validados
    conta: ContaPlanejada
    perfil: PerfilSnapshot
    gestor: GestorSnapshot
    data_admissao: date
    data_licenca: date | None
    historico: list[Evento] = Field(default_factory=list)
    versao: int = 1

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def pendente(self) -> bool:
        return self.status == "enviada"

    def eh_do_solicitante(self, oid: str) -> bool:
        return self.solicitante.oid.lower() == oid.lower()


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
    return _transition(req, aprovador, "aprovada", _clean_comment(comentario))


def reject(req: ProvisioningRequest, aprovador: Pessoa, comentario: str) -> ProvisioningRequest:
    if req.status != "enviada":
        raise WorkflowError(f"A solicitação está '{req.status_label}' e não pode ser rejeitada.")
    if req.eh_do_solicitante(aprovador.oid):
        raise WorkflowError("Você não pode rejeitar uma solicitação feita por você.")
    texto = _clean_comment(comentario)
    if len(texto) < COMMENT_MIN:
        raise WorkflowError(f"Informe o motivo da rejeição (mínimo de {COMMENT_MIN} caracteres).")
    return _transition(req, aprovador, "rejeitada", texto)


def cancel(
    req: ProvisioningRequest, ator: Pessoa, *, is_admin: bool = False, comentario: str = ""
) -> ProvisioningRequest:
    if req.status != "enviada":
        raise WorkflowError(f"A solicitação está '{req.status_label}' e não pode ser cancelada.")
    if not (is_admin or req.eh_do_solicitante(ator.oid)):
        raise WorkflowError("Somente quem fez a solicitação (ou um administrador) pode cancelá-la.")
    return _transition(req, ator, "cancelada", _clean_comment(comentario))
