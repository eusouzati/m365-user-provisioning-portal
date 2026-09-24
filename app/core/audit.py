"""Trilha de auditoria (Sprint 9).

Cada evento registra quem fez o quê, quando e sobre qual objeto. Regras:
- somente acréscimo (append-only): o portal não altera nem apaga eventos;
- nunca contém senha, TAP, token ou segredo;
- minimização (LGPD): o alvo é identificado pelo número da solicitação ou do perfil;
  nomes, UPNs e e-mails do colaborador ficam na solicitação (que pode ser anonimizada),
  não no evento. O ator (quem executou) é mantido para responsabilização.
"""

from __future__ import annotations

import contextvars
import re
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

ACOES: dict[str, str] = {
    "solicitacao.enviada": "Solicitação enviada",
    "solicitacao.aprovada": "Solicitação aprovada",
    "solicitacao.rejeitada": "Solicitação rejeitada",
    "solicitacao.cancelada": "Solicitação cancelada",
    "solicitacao.registro": "Registro no histórico",
    "acesso_inicial.gerado": "Acesso inicial (TAP) gerado",
    "conta.criada": "Conta criada (desativada)",
    "conta.licenciada": "Licença atribuída",
    "conta.ativada": "Conta ativada",
    "conta.desligada": "Desligamento concluído",
    "execucao.falha": "Falha parcial",
    "etapa.ok": "Etapa concluída",
    "etapa.falhou": "Etapa com falha",
    "etapa.manual": "Ação manual registrada",
    "perfil.criado": "Perfil criado",
    "perfil.alterado": "Perfil alterado",
    "perfil.excluido": "Perfil excluído",
    "ciclo.executado": "Agendador executado",
    "lgpd.anonimizado": "Dados pessoais anonimizados",
    "auditoria.exportada": "Auditoria exportada",
}

STATUS_ACAO: dict[str, str] = {
    "enviada": "solicitacao.enviada",
    "aprovada": "solicitacao.aprovada",
    "rejeitada": "solicitacao.rejeitada",
    "cancelada": "solicitacao.cancelada",
    "conta_criada": "conta.criada",
    "licenciada": "conta.licenciada",
    "ativa": "conta.ativada",
    "desligada": "conta.desligada",
    "falha_parcial": "execucao.falha",
}

DETALHE_MAX = 300

_EMAIL = re.compile(r"[^\s;:,()<>\"']+@[^\s;:,()<>\"']+")
# etapas são unidas por "; " — o nome vai até o próximo ";" (nomes podem ter "." como "S.")
_GESTOR = re.compile(r"(Definir gestor)(?:: [^;\n]*)?")


def redact(texto: str) -> str:
    """Remove dados pessoais conhecidos de textos do sistema (e-mails/UPNs e o nome do
    gestor que aparece no nome da etapa "Definir gestor: <nome>")."""
    texto = _EMAIL.sub("[e-mail]", texto or "")
    return _GESTOR.sub(r"\1", texto)


def safe_step_name(chave: str, nome: str) -> str:
    """Nome de etapa sem dados pessoais (grupos e licenças não são dados pessoais)."""
    if chave == "definir_gestor":
        return "Definir gestor"
    if chave == "manual:subordinados":
        return "Definir novo gestor para os subordinados"
    return redact(nome)


class AuditEvent(BaseModel):
    id: str = ""
    em: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ator_oid: str
    ator_nome: str
    acao: str
    alvo: str = ""  # REQ-… ou perfil:<id>
    tipo: str = ""  # admissao | desligamento (solicitações)
    detalhe: str = ""

    def model_post_init(self, __context) -> None:
        if not self.id:
            # ordenável pelo tempo e único
            self.id = f"{self.em:%Y%m%d%H%M%S%f}-{uuid.uuid4().hex[:8]}"
        self.detalhe = " ".join(self.detalhe.split())[:DETALHE_MAX]

    @property
    def acao_label(self) -> str:
        return ACOES.get(self.acao, self.acao)


# ----------------------------------------------------------- ator da requisição
# O middleware cria um "recipiente" por requisição; a dependência de autenticação
# preenche o ator. (Um dicionário mutável atravessa as cópias de contexto que o
# Starlette faz ao executar rotas síncronas em threads.)
_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("m365up_audit", default=None)

SISTEMA_OID, SISTEMA_NOME = "sistema", "Portal (automático)"


def begin_request() -> contextvars.Token:
    return _ctx.set({})


def end_request(token: contextvars.Token) -> None:
    _ctx.reset(token)


def set_actor(oid: str, nome: str) -> None:
    holder = _ctx.get()
    if holder is not None:
        holder["actor"] = (oid, nome)


def current_actor() -> tuple[str, str]:
    holder = _ctx.get()
    if holder and holder.get("actor"):
        return holder["actor"]
    return SISTEMA_OID, SISTEMA_NOME


class AuditContextMiddleware:
    """Middleware ASGI: um recipiente de ator por requisição."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = begin_request()
        try:
            await self.app(scope, receive, send)
        finally:
            end_request(token)
