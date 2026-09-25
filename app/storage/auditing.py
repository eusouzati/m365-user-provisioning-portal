"""Registro automático de auditoria em volta do armazenamento.

Toda gravação de solicitação ou perfil passa por aqui; os eventos são deduzidos da
diferença entre a versão anterior e a nova (transições do histórico e etapas concluídas
ou com falha). Assim nenhuma rota precisa lembrar de auditar — e nada escapa.
Uma falha ao gravar a auditoria é registrada no log, mas não desfaz a operação.
"""

from __future__ import annotations

import logging

from app.core.audit import STATUS_ACAO, AuditEvent, current_actor, redact, safe_step_name
from app.core.profiles import OnboardingProfile
from app.core.workflow import ANON_NOTE, ProvisioningRequest
from app.storage.base import StorageBackend

logger = logging.getLogger("m365up.auditoria")

_ETAPA_ACAO = {"ok": "etapa.ok", "falhou": "etapa.falhou", "manual": "etapa.manual"}


def request_events(old: ProvisioningRequest | None, new: ProvisioningRequest) -> list[AuditEvent]:
    eventos: list[AuditEvent] = []
    antes = len(old.historico) if old else 0
    for ev in new.historico[antes:]:
        if ev.de == ev.para:
            if ev.comentario.startswith(ANON_NOTE):
                acao = "lgpd.anonimizado"
            elif ev.comentario.startswith("Acesso inicial gerado") or "TAP" in ev.comentario:
                acao = "acesso_inicial.gerado"
            else:
                acao = "solicitacao.registro"
        else:
            acao = STATUS_ACAO.get(ev.para, f"solicitacao.{ev.para}")
        # Comentários de pessoas ficam só na solicitação (minimização); textos do
        # sistema (etapas, falhas) vão para a auditoria.
        humano = ev.ator.oid != "sistema" and not acao.startswith(("acesso", "lgpd"))
        detalhe = "" if humano else redact(ev.comentario)
        eventos.append(
            AuditEvent(
                em=ev.em,
                ator_oid=ev.ator.oid,
                ator_nome=ev.ator.nome,
                acao=acao,
                alvo=new.id,
                tipo=new.tipo,
                detalhe=detalhe,
            )
        )
    anteriores = {e.chave: e.status for e in (old.etapas if old else [])}
    oid, nome = current_actor()
    for e in new.etapas:
        acao = _ETAPA_ACAO.get(e.status)
        if acao and anteriores.get(e.chave) != e.status:
            nome_etapa = safe_step_name(e.chave, e.nome)
            detalhe = nome_etapa if e.status != "falhou" else f"{nome_etapa}: {redact(e.detalhe)}"
            extra = {"em": e.em} if e.em else {}
            eventos.append(
                AuditEvent(
                    ator_oid=oid,
                    ator_nome=nome,
                    acao=acao,
                    alvo=new.id,
                    tipo=new.tipo,
                    detalhe=detalhe,
                    **extra,
                )
            )
    return eventos


class AuditingStorage:
    """Mesmo contrato do StorageBackend; delega tudo e audita as gravações."""

    def __init__(self, inner: StorageBackend) -> None:
        self._inner = inner
        self.name = inner.name

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def record(self, event: AuditEvent) -> None:
        try:
            self._inner.append_audit(event)
        except Exception:  # auditoria nunca derruba a operação principal
            logger.exception("Falha ao gravar evento de auditoria %s", event.acao)

    def _record_all(self, eventos: list[AuditEvent]) -> None:
        for ev in eventos:
            self.record(ev)

    # ---------------------------------------------------------- solicitações
    def create_request(self, req: ProvisioningRequest) -> None:
        self._inner.create_request(req)
        self._record_all(request_events(None, req))

    def append_audit(self, event: AuditEvent) -> None:
        self.record(event)  # mesmo pelo wrapper, uma falha nunca derruba a operação

    def update_request(self, req: ProvisioningRequest) -> ProvisioningRequest:
        try:
            old = self._inner.get_request(req.id)
        except Exception:
            old = None
        novo = self._inner.update_request(req)
        if old is None:
            # Sem a versão anterior, registra só o último evento (evita duplicar o histórico).
            old = novo.model_copy(update={"historico": novo.historico[:-1], "etapas": []})
            eventos = [e for e in request_events(old, novo) if not e.acao.startswith("etapa.")]
        else:
            eventos = request_events(old, novo)
        self._record_all(eventos)
        return novo

    # --------------------------------------------------------------- perfis
    def save_profile(self, profile: OnboardingProfile) -> None:
        existia = self._inner.get_profile(profile.id) is not None
        self._inner.save_profile(profile)
        oid, nome = current_actor()
        self.record(
            AuditEvent(
                ator_oid=oid,
                ator_nome=nome,
                acao="perfil.alterado" if existia else "perfil.criado",
                alvo=f"perfil:{profile.id}",
                detalhe=profile.nome,
            )
        )

    def delete_profile(self, profile_id: str) -> None:
        perfil = self._inner.get_profile(profile_id)
        self._inner.delete_profile(profile_id)
        oid, nome = current_actor()
        self.record(
            AuditEvent(
                ator_oid=oid,
                ator_nome=nome,
                acao="perfil.excluido",
                alvo=f"perfil:{profile_id}",
                detalhe=perfil.nome if perfil else "",
            )
        )
