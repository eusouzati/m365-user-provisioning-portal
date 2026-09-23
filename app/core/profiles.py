"""Perfis de onboarding: departamento/tipo de colaborador → grupos de acesso + licença.

Regra de segurança: o navegador só envia IDs; o backend aceita apenas IDs que existem no
tenant e passam pelas regras abaixo. Grupos de papéis do portal, grupos com atribuição de
função e grupos dinâmicos nunca são aceitos.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.graph.models import Group, SubscribedSku

TipoColaborador = Literal["funcionario", "estagiario", "terceiro", "temporario"]

TIPOS_COLABORADOR: dict[str, str] = {
    "funcionario": "Funcionário",
    "estagiario": "Estagiário",
    "terceiro": "Terceiro",
    "temporario": "Temporário",
}

MAX_GRUPOS_ACESSO = 20


class GroupRef(BaseModel):
    id: str
    nome: str


class SkuRef(BaseModel):
    sku_id: str
    part_number: str


class OnboardingProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nome: str = Field(min_length=3, max_length=80)
    departamento: str = Field(min_length=1, max_length=80)
    tipo_colaborador: TipoColaborador
    grupos_acesso: list[GroupRef] = Field(default_factory=list)
    grupo_licenca: GroupRef | None = None
    sku_licenca: SkuRef | None = None
    ativo: bool = True
    atualizado_por: str = ""
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("nome", "departamento")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if any(c in v for c in "<>\"'`"):
            raise ValueError("caracteres não permitidos")
        return v


class ProfileValidationError(ValueError):
    def __init__(self, erros: list[str]) -> None:
        super().__init__("; ".join(erros))
        self.erros = erros


def _group_problem(g: Group, protected: frozenset[str]) -> str | None:
    if g.id.lower() in protected:
        return "é um grupo de papel do portal"
    if g.is_role_assignable:
        return "permite atribuição de funções administrativas"
    if g.is_dynamic:
        return "é dinâmico (membros não podem ser adicionados manualmente)"
    if not g.security_enabled:
        return "não é um grupo de segurança"
    return None


def eligible_access_groups(groups: list[Group], protected: frozenset[str]) -> list[Group]:
    return [g for g in groups if not _group_problem(g, protected) and not g.is_license_group]


def eligible_license_groups(groups: list[Group], protected: frozenset[str]) -> list[Group]:
    return [g for g in groups if not _group_problem(g, protected) and g.is_license_group]


def eligible_skus(skus: list[SubscribedSku]) -> list[SubscribedSku]:
    return [s for s in skus if s.capability_status == "Enabled" and s.applies_to == "User"]


def resolve_selection(
    *,
    access_group_ids: list[str],
    license_group_id: str | None,
    sku_id: str | None,
    groups: list[Group],
    skus: list[SubscribedSku],
    protected: frozenset[str],
    license_mode: str,
) -> tuple[list[GroupRef], GroupRef | None, SkuRef | None]:
    """Valida os IDs recebidos do navegador contra o tenant. Levanta ProfileValidationError."""
    by_id = {g.id.lower(): g for g in groups}
    erros: list[str] = []

    ids = list(dict.fromkeys(i.strip() for i in access_group_ids if i.strip()))
    if len(ids) > MAX_GRUPOS_ACESSO:
        erros.append(f"No máximo {MAX_GRUPOS_ACESSO} grupos de acesso por perfil.")
    acesso: list[GroupRef] = []
    for gid in ids:
        g = by_id.get(gid.lower())
        if not g:
            erros.append("Um dos grupos selecionados não existe mais no tenant.")
            continue
        problem = _group_problem(g, protected)
        if problem:
            erros.append(f"O grupo '{g.display_name}' não pode ser usado: {problem}.")
        elif g.is_license_group:
            erros.append(
                f"O grupo '{g.display_name}' atribui licença; selecione-o como grupo de licença."
            )
        else:
            acesso.append(GroupRef(id=g.id, nome=g.display_name))

    grupo_licenca: GroupRef | None = None
    sku_ref: SkuRef | None = None
    if license_mode == "group":
        if sku_id:
            erros.append("Com LICENSE_MODE=group a licença é definida por grupo, não por SKU.")
        if license_group_id:
            g = by_id.get(license_group_id.strip().lower())
            if not g:
                erros.append("O grupo de licença selecionado não existe mais no tenant.")
            elif problem := _group_problem(g, protected):
                erros.append(f"O grupo '{g.display_name}' não pode ser usado: {problem}.")
            elif not g.is_license_group:
                erros.append(f"O grupo '{g.display_name}' não atribui nenhuma licença.")
            else:
                grupo_licenca = GroupRef(id=g.id, nome=g.display_name)
    else:
        if license_group_id:
            erros.append("Com LICENSE_MODE=direct a licença é definida por SKU, não por grupo.")
        if sku_id:
            s = next((s for s in eligible_skus(skus) if s.sku_id.lower() == sku_id.lower()), None)
            if not s:
                erros.append("A licença selecionada não está disponível no tenant.")
            else:
                sku_ref = SkuRef(sku_id=s.sku_id, part_number=s.sku_part_number)

    if erros:
        raise ProfileValidationError(erros)
    return acesso, grupo_licenca, sku_ref
