from __future__ import annotations

import pytest

from app.core.naming import (
    NamingError,
    ascii_fold,
    build_local_part,
    candidates,
    generate_account_names,
    slug,
    validate_pattern,
)


@pytest.mark.parametrize(
    ("nome", "sobrenome", "esperado"),
    [
        ("João", "da Silva", "joao.silva"),
        ("Maria José", "dos Santos Conceição", "maria.conceicao"),
        ("José", "D'Ávila", "jose.davila"),
        ("Ana-Maria", "Souza e Lima", "ana-maria.lima"),
        ("Çağla", "Öztürk", "cagla.ozturk"),
        ("Jürgen", "Weiß", "jurgen.weiss"),
        ("Łukasz", "Nowak", "lukasz.nowak"),
        ("  Pedro  ", "  de   Alcântara  ", "pedro.alcantara"),
        ("Ñandú", "Peña", "nandu.pena"),
        ("Jean", "Van", "jean.van"),  # sobrenome só com partícula: mantém
    ],
)
def test_nomes_brasileiros_e_estrangeiros(nome, sobrenome, esperado):
    assert build_local_part(nome, sobrenome) == esperado


@pytest.mark.parametrize(
    ("padrao", "esperado"),
    [
        ("{nome}.{ultimo_sobrenome}", "joao.pereira"),
        ("{nome}.{primeiro_sobrenome}", "joao.silva"),
        ("{inicial_nome}{ultimo_sobrenome}", "jpereira"),
        ("{nome}_{sobrenomes}", "joao_silva.pereira"),
    ],
)
def test_padroes(padrao, esperado):
    assert build_local_part("João Carlos", "da Silva Pereira", padrao) == esperado


@pytest.mark.parametrize("padrao", ["", "fixo", "{cpf}", "{nome}@{ultimo_sobrenome}", "{nome} x"])
def test_padroes_invalidos(padrao):
    with pytest.raises(NamingError):
        validate_pattern(padrao)


def test_nome_sem_letras_utilizaveis():
    with pytest.raises(NamingError):
        build_local_part("李", "王")
    with pytest.raises(NamingError):
        build_local_part("João", "!!!")


def test_helpers():
    assert ascii_fold("Conceição Ávila") == "Conceicao Avila"
    assert slug("O’Brien") == "obrien"
    assert list(candidates("joao.silva", 3)) == ["joao.silva", "joao.silva2", "joao.silva3"]


def test_limite_de_64_caracteres():
    local = build_local_part("A" * 40, "B" * 40)
    assert len(local) <= 64 and not local.endswith(".")
    ultimo = list(candidates(local, 12))[-1]
    assert len(ultimo) <= 64 and ultimo.endswith("12")


def test_geracao_resolve_duplicados():
    ocupados = {"joao.silva@contoso.com", "joao.silva2@contoso.com"}
    nomes = generate_account_names(
        first_name="João",
        surname="da Silva",
        domain="Contoso.com",
        is_taken=lambda addr, nick: addr in ocupados,
    )
    assert nomes.user_principal_name == "joao.silva3@contoso.com"
    assert nomes.mail == nomes.user_principal_name
    assert nomes.mail_nickname == "joao.silva3"
    assert nomes.display_name == "João da Silva"
    assert (nomes.given_name, nomes.surname) == ("João", "da Silva")
    assert nomes.renamed and nomes.attempts == 2


def test_display_name_personalizado():
    nomes = generate_account_names(
        first_name="João",
        surname="Silva",
        domain="contoso.com",
        is_taken=lambda a, n: False,
        display="João S. (Financeiro)",
    )
    assert nomes.display_name == "João S. (Financeiro)" and not nomes.renamed


def test_sem_login_livre():
    with pytest.raises(NamingError):
        generate_account_names(
            first_name="Ana",
            surname="Lima",
            domain="contoso.com",
            is_taken=lambda a, n: True,
            limit=3,
        )


@pytest.mark.parametrize("dominio", ["", "contoso", "-x.com", "a b.com", "contoso.com/evil"])
def test_dominio_invalido(dominio):
    with pytest.raises(NamingError):
        generate_account_names(
            first_name="Ana", surname="Lima", domain=dominio, is_taken=lambda a, n: False
        )
