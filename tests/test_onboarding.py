"""Revisão da solicitação (regras de negócio com Graph simulado)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.profiles import GroupRef, OnboardingProfile
from app.core.requests import NewHireForm
from app.graph.directory import DirectoryCache
from app.graph.fake import FakeGraphService
from app.services.onboarding import ReviewError, build_review
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_settings

HOJE = date(2026, 9, 23)


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path, auth_mode="dev", m365_default_domain="contoso.com")
    storage = SqliteStorage(str(tmp_path / "t.db"))
    graph = FakeGraphService()
    perfil = OnboardingProfile(
        id="p-fin",
        nome="Financeiro — Funcionário",
        departamento="Financeiro",
        tipo_colaborador="funcionario",
        grupos_acesso=[GroupRef(id="g-fin", nome="Financeiro")],
        grupo_licenca=GroupRef(id="g-lic-e3", nome="Licença - Microsoft 365 E3"),
    )
    storage.save_profile(perfil)
    storage.save_profile(
        perfil.model_copy(
            update={
                "id": "p-sem",
                "nome": "Terceiro sem licença",
                "tipo_colaborador": "terceiro",
                "grupo_licenca": None,
            }
        )
    )
    storage.save_profile(
        perfil.model_copy(update={"id": "p-off", "nome": "Inativo", "ativo": False})
    )
    return settings, storage, graph, DirectoryCache(graph)


def form(**kw):
    base = {
        "nome": "João",
        "sobrenome": "da Silva",
        "matricula": "2001",
        "cargo": "Analista",
        "departamento": "Financeiro",
        "data_admissao": HOJE + timedelta(days=10),
        "gestor_id": "u-1",
        "tipo_colaborador": "funcionario",
        "perfil_id": "p-fin",
    }
    base.update(kw)
    return NewHireForm.model_validate(base)


def review(env, f):
    settings, storage, graph, directory = env
    return build_review(
        f, settings=settings, graph=graph, directory=directory, storage=storage, today=HOJE
    )


def test_revisao_completa_com_nome_duplicado(env):
    r = review(env, form())
    assert r.names.user_principal_name == "joao.silva2@contoso.com"  # joao.silva já existe
    assert any("já está em uso" in a for a in r.avisos)
    assert r.gestor.display_name == "Ana Gestora"
    assert r.data_licenca == HOJE + timedelta(days=9)  # D-1
    assert r.data_ativacao == HOJE + timedelta(days=10)
    assert not r.licenca_imediata and not r.ativacao_imediata


def test_admissao_amanha_licenca_imediata(env):
    r = review(env, form(data_admissao=HOJE + timedelta(days=1)))
    assert r.licenca_imediata and not r.ativacao_imediata


def test_admissao_passada_gera_aviso(env):
    r = review(env, form(data_admissao=HOJE - timedelta(days=2)))
    assert r.ativacao_imediata and any("já passou" in a for a in r.avisos)


def test_perfil_sem_licenca(env):
    r = review(env, form(tipo_colaborador="terceiro", perfil_id="p-sem"))
    assert r.data_licenca is None and any("não atribui licença" in a for a in r.avisos)


@pytest.mark.parametrize(
    ("campos", "trecho"),
    [
        ({"perfil_id": "p-off"}, "inativo"),
        ({"perfil_id": "nao-existe"}, "inexistente"),
        ({"tipo_colaborador": "estagiario"}, "é para Funcionário"),
        ({"gestor_id": "u-999"}, "Gestor não encontrado"),
        ({"gestor_id": "u-4"}, "desativada"),
        ({"matricula": "1001"}, "matrícula 1001"),
        ({"data_admissao": HOJE - timedelta(days=31)}, "muito antiga"),
        ({"data_admissao": HOJE + timedelta(days=366)}, "muito distante"),
    ],
)
def test_bloqueios(env, campos, trecho):
    with pytest.raises(ReviewError) as exc:
        review(env, form(**campos))
    assert trecho in " ".join(exc.value.erros)


def test_dominio_nao_verificado(env):
    settings, storage, graph, directory = env
    s = settings.model_copy(update={"m365_default_domain": "outro.com"})
    with pytest.raises(ReviewError, match="não está verificado"):
        build_review(
            form(), settings=s, graph=graph, directory=directory, storage=storage, today=HOJE
        )


def test_varios_erros_de_uma_vez(env):
    with pytest.raises(ReviewError) as exc:
        review(env, form(gestor_id="u-999", matricula="1001"))
    assert len(exc.value.erros) == 2


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("nome", "Jo<script>"),
        ("nome", "João123"),
        ("sobrenome", ""),
        ("matricula", "12 34"),
        ("matricula", "X" * 17),
        ("cargo", 'Analista "sênior"'),
        ("tipo_colaborador", "chefe"),
        ("gestor_id", "../../users"),
    ],
)
def test_formulario_rejeita_valores(campo, valor):
    with pytest.raises(ValueError):
        form(**{campo: valor})


def test_formulario_normaliza_espacos():
    f = form(nome="  Maria   José ", cargo=" Analista   Pleno ")
    assert (f.nome, f.cargo) == ("Maria José", "Analista Pleno")
    assert form(sobrenome="D'Ávila-Neto").sobrenome == "D'Ávila-Neto"
