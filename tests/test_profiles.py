from __future__ import annotations

import pytest

from app.core.profiles import (
    OnboardingProfile,
    ProfileValidationError,
    eligible_access_groups,
    eligible_license_groups,
    resolve_selection,
)
from app.graph.fake import FakeGraphService

G = FakeGraphService()
PROT = frozenset({"g-portal-adm"})


def resolve(ids=(), lic=None, sku=None, mode="group"):
    return resolve_selection(
        access_group_ids=list(ids),
        license_group_id=lic,
        sku_id=sku,
        groups=G.groups,
        skus=G.skus,
        protected=PROT,
        license_mode=mode,
    )


def test_elegiveis():
    acesso = {g.id for g in eligible_access_groups(G.groups, PROT)}
    assert acesso == {"g-fin", "g-rh", "g-ti", "g-vpn"}
    assert {g.id for g in eligible_license_groups(G.groups, PROT)} == {"g-lic-e3"}


def test_selecao_valida():
    acesso, lic, sku = resolve(["g-fin", "g-vpn", "g-fin"], "g-lic-e3")
    assert [g.id for g in acesso] == ["g-fin", "g-vpn"]  # duplicado removido
    assert lic.id == "g-lic-e3" and sku is None


@pytest.mark.parametrize(
    ("ids", "trecho"),
    [
        (["g-portal-adm"], "papel do portal"),
        (["G-PORTAL-ADM"], "papel do portal"),
        (["g-admins"], "funções administrativas"),
        (["g-dyn"], "dinâmico"),
        (["g-all"], "segurança"),
        (["g-lic-e3"], "atribui licença"),
        (["id-inventado"], "não existe"),
    ],
)
def test_grupos_recusados(ids, trecho):
    with pytest.raises(ProfileValidationError) as exc:
        resolve(ids)
    assert trecho in " ".join(exc.value.erros)


def test_grupo_de_licenca_invalido():
    with pytest.raises(ProfileValidationError):
        resolve([], "g-fin")
    with pytest.raises(ProfileValidationError):
        resolve([], "g-portal-adm")


def test_modo_direto():
    _, lic, sku = resolve([], None, "05e9a617-0261-4cee-bb44-138d3ef5d965", mode="direct")
    assert lic is None and sku.part_number == "SPE_E3"
    with pytest.raises(ProfileValidationError):
        resolve([], "g-lic-e3", mode="direct")
    with pytest.raises(ProfileValidationError):
        resolve([], None, "sku-inexistente", mode="direct")


def test_limite_de_grupos():
    with pytest.raises(ProfileValidationError):
        resolve([f"x{i}" for i in range(21)])


def test_modelo_normaliza_e_rejeita_html():
    p = OnboardingProfile(
        nome="  Financeiro   Funcionário ", departamento="Fin", tipo_colaborador="funcionario"
    )
    assert p.nome == "Financeiro Funcionário"
    with pytest.raises(ValueError):
        OnboardingProfile(nome="<script>", departamento="x", tipo_colaborador="funcionario")
