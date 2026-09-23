"""Revisão de uma solicitação de novo colaborador.

Tudo aqui é recalculado no servidor a partir dos campos do formulário — nada que o
navegador exibiu na revisão (UPN, grupos, datas) é aceito como verdade.
Somente leitura: nenhuma escrita no Microsoft 365.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.core.naming import AccountNames, NamingError, generate_account_names
from app.core.profiles import TIPOS_COLABORADOR, OnboardingProfile
from app.core.requests import NewHireForm
from app.graph.directory import DirectoryCache
from app.graph.models import UserSummary
from app.graph.service import GraphService
from app.storage import StorageBackend


class ReviewError(ValueError):
    def __init__(self, erros: list[str]) -> None:
        super().__init__("; ".join(erros))
        self.erros = erros


@dataclass
class Review:
    form: NewHireForm
    names: AccountNames
    perfil: OnboardingProfile
    gestor: UserSummary
    hoje: date
    data_licenca: date | None  # None = perfil sem licença
    data_ativacao: date
    avisos: list[str] = field(default_factory=list)

    @property
    def licenca_imediata(self) -> bool:
        return self.data_licenca is not None and self.data_licenca <= self.hoje

    @property
    def ativacao_imediata(self) -> bool:
        return self.data_ativacao <= self.hoje

    @property
    def tipo_label(self) -> str:
        return TIPOS_COLABORADOR[self.form.tipo_colaborador]


def today_in(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def build_review(
    form: NewHireForm,
    *,
    settings: Settings,
    graph: GraphService,
    directory: DirectoryCache,
    storage: StorageBackend,
    today: date | None = None,
    reserved_upns: frozenset[str] = frozenset(),
    reserved_employee_ids: dict[str, str] | None = None,
) -> Review:
    """``reserved_*``: UPNs e matrículas de outras solicitações ainda em andamento."""
    hoje = today or today_in(settings)
    erros: list[str] = []
    avisos: list[str] = []

    # Domínio
    dominio = settings.m365_default_domain.strip().lower()
    verificados = {d.name.lower() for d in directory.domains() if d.is_verified}
    if not dominio:
        erros.append("M365_DEFAULT_DOMAIN não está configurado. Fale com o administrador.")
    elif dominio not in verificados:
        erros.append(f"O domínio '{dominio}' não está verificado no tenant.")

    # Data de admissão
    minimo = hoje - timedelta(days=settings.hire_date_past_days)
    maximo = hoje + timedelta(days=settings.hire_date_future_days)
    if form.data_admissao < minimo:
        erros.append(f"Data de admissão muito antiga (mínimo: {minimo:%d/%m/%Y}).")
    elif form.data_admissao > maximo:
        erros.append(f"Data de admissão muito distante (máximo: {maximo:%d/%m/%Y}).")
    elif form.data_admissao < hoje:
        avisos.append("A data de admissão já passou: a conta será ativada assim que aprovada.")

    # Perfil
    perfil = storage.get_profile(form.perfil_id)
    if not perfil or not perfil.ativo:
        erros.append("Perfil de onboarding inexistente ou inativo.")
    elif perfil.tipo_colaborador != form.tipo_colaborador:
        erros.append(
            f"O perfil '{perfil.nome}' é para {TIPOS_COLABORADOR[perfil.tipo_colaborador]}, "
            f"mas o tipo informado é {TIPOS_COLABORADOR[form.tipo_colaborador]}."
        )
    elif perfil.departamento.casefold() != form.departamento.casefold():
        avisos.append(
            f"O departamento informado ({form.departamento}) difere do departamento do perfil "
            f"({perfil.departamento})."
        )

    # Gestor
    gestor = graph.get_user(form.gestor_id)
    if not gestor:
        erros.append("Gestor não encontrado no diretório.")
    elif not gestor.account_enabled:
        erros.append(f"O gestor '{gestor.display_name}' está com a conta desativada.")

    # Matrícula
    if graph.find_users_by_employee_id(form.matricula):
        erros.append(f"A matrícula {form.matricula} já pertence a outro usuário do tenant.")
    elif outra := (reserved_employee_ids or {}).get(form.matricula):
        erros.append(f"A matrícula {form.matricula} já está na solicitação {outra}, em andamento.")

    # Nomes / UPN
    names = None
    if dominio and dominio in verificados:
        try:
            names = generate_account_names(
                first_name=form.nome,
                surname=form.sobrenome,
                display=form.nome_exibicao or None,
                domain=dominio,
                pattern=settings.upn_pattern,
                particles=settings.particles,
                is_taken=lambda addr, nick: (
                    addr.lower() in reserved_upns or bool(graph.find_address_conflicts(addr, nick))
                ),
            )
        except NamingError as exc:
            erros.append(str(exc))

    if erros:
        raise ReviewError(erros)

    assert names and perfil and gestor  # noqa: S101 — garantido pelas validações acima
    if names.renamed:
        avisos.append(
            f"O login {names.base_local_part}@{dominio} já está em uso (no tenant ou em outra "
            f"solicitação em andamento); será usado {names.user_principal_name}."
        )

    tem_licenca = bool(perfil.grupo_licenca or perfil.sku_licenca)
    data_licenca = (
        form.data_admissao - timedelta(days=settings.license_lead_days) if tem_licenca else None
    )
    if not tem_licenca:
        avisos.append("O perfil não atribui licença: o colaborador não terá e-mail nem Office.")

    return Review(
        form=form,
        names=names,
        perfil=perfil,
        gestor=gestor,
        hoje=hoje,
        data_licenca=data_licenca,
        data_ativacao=form.data_admissao,
        avisos=avisos,
    )
