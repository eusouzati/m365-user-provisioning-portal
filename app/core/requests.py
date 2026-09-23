"""Formulário de novo colaborador — validação dos campos (sem acesso ao Graph)."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.profiles import TipoColaborador

# Letras (inclusive acentuadas) separadas por espaço, hífen, apóstrofo ou ponto
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[\s'’.-]+[^\W\d_]+)*\.?$")
_FORBIDDEN = re.compile(r"[<>\"`\x00-\x1f\x7f]")

Texto = Annotated[str, StringConstraints(strip_whitespace=True)]

CAMPOS = {
    "nome": "Nome",
    "sobrenome": "Sobrenome",
    "nome_exibicao": "Nome de exibição",
    "matricula": "Matrícula",
    "cargo": "Cargo",
    "departamento": "Departamento",
    "empresa": "Empresa",
    "unidade": "Unidade",
    "cidade": "Cidade",
    "estado": "Estado",
    "pais": "País",
    "data_admissao": "Data de admissão",
    "gestor_id": "Gestor",
    "tipo_colaborador": "Tipo de colaborador",
    "perfil_id": "Perfil de onboarding",
}


def _clean(v: str) -> str:
    v = " ".join(v.split())
    if _FORBIDDEN.search(v):
        raise ValueError("contém caracteres não permitidos")
    return v


class NewHireForm(BaseModel):
    """Campos enviados pelo RH. Limites seguem os do Microsoft Graph."""

    model_config = ConfigDict(extra="ignore")

    nome: Texto = Field(min_length=1, max_length=64)
    sobrenome: Texto = Field(min_length=1, max_length=64)
    nome_exibicao: Texto = Field(default="", max_length=256)
    matricula: Texto = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")
    cargo: Texto = Field(min_length=1, max_length=128)
    departamento: Texto = Field(min_length=1, max_length=64)
    empresa: Texto = Field(default="", max_length=64)
    unidade: Texto = Field(default="", max_length=128)
    cidade: Texto = Field(default="", max_length=128)
    estado: Texto = Field(default="", max_length=128)
    pais: Texto = Field(default="", max_length=128)
    data_admissao: date
    gestor_id: Texto = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    tipo_colaborador: TipoColaborador
    perfil_id: Texto = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")

    @field_validator("nome", "sobrenome")
    @classmethod
    def _nome_pessoa(cls, v: str) -> str:
        v = _clean(v)
        if not _NAME_RE.match(v):
            raise ValueError("use apenas letras, espaços, hífen ou apóstrofo")
        return v

    @field_validator(
        "nome_exibicao", "cargo", "departamento", "empresa", "unidade", "cidade", "estado", "pais"
    )
    @classmethod
    def _texto(cls, v: str) -> str:
        return _clean(v)


def friendly_errors(exc) -> list[str]:
    """Converte erros do pydantic em mensagens em português por campo."""
    msgs = []
    for e in exc.errors():
        campo = CAMPOS.get(str(e["loc"][0]) if e.get("loc") else "", "Campo")
        tipo = e.get("type", "")
        if tipo in ("missing", "string_too_short") or (
            tipo == "literal_error" and not e.get("input")
        ):
            msgs.append(f"{campo}: obrigatório.")
        elif tipo == "string_too_long":
            msgs.append(f"{campo}: máximo de {e['ctx']['max_length']} caracteres.")
        elif tipo == "string_pattern_mismatch":
            msgs.append(f"{campo}: formato inválido.")
        elif tipo.startswith("date"):
            msgs.append(f"{campo}: data inválida.")
        elif tipo == "literal_error":
            msgs.append(f"{campo}: opção inválida.")
        else:
            msg = str(e.get("msg", "inválido")).removeprefix("Value error, ")
            msgs.append(f"{campo}: {msg}.")
    return list(dict.fromkeys(msgs))
