"""Formulário de desligamento — validação dos campos (sem acesso ao Graph)."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.graph.models import Group

# Object ID vindo da busca no diretório (GUID no Graph real; o GraphService valida de novo)
_OBJECT_ID = r"^[0-9A-Za-z-]{1,64}$"
_FORBIDDEN = re.compile(r"[<>\"`\x00-\x1f\x7f]")

Texto = Annotated[str, StringConstraints(strip_whitespace=True)]

CAMPOS = {
    "colaborador_id": "Colaborador",
    "data_desligamento": "Último dia de trabalho",
    "observacao": "Observação",
}


class OffboardingForm(BaseModel):
    """Campos enviados pelo RH. O colaborador vem da busca no diretório (Object ID)."""

    model_config = ConfigDict(extra="ignore")

    colaborador_id: Texto = Field(pattern=_OBJECT_ID)
    colaborador_nome: Texto = Field(default="", max_length=256)
    data_desligamento: date
    imediato: bool = False
    observacao: Texto = Field(default="", max_length=500)

    @field_validator("imediato", mode="before")
    @classmethod
    def _checkbox(cls, v):
        return str(v).lower() in ("on", "true", "1", "sim")

    @field_validator("colaborador_nome", "observacao")
    @classmethod
    def _texto(cls, v: str) -> str:
        v = " ".join(v.split())
        if _FORBIDDEN.search(v):
            raise ValueError("contém caracteres não permitidos")
        return v


def friendly_errors(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        campo = CAMPOS.get(str(err["loc"][0]) if err["loc"] else "", "Campo")
        if campo == "Colaborador":
            out.append("Selecione o colaborador na busca.")
        elif err["type"].startswith("date"):
            out.append(f"{campo}: informe uma data válida.")
        else:
            out.append(f"{campo}: valor inválido.")
    return sorted(set(out))


def classify_group(g: Group) -> str:
    """'' se o portal pode remover o usuário do grupo; senão, o motivo (ação manual)."""
    if g.on_premises:
        return "Grupo sincronizado do AD local: remova no Active Directory."
    if g.is_dynamic:
        return "Grupo dinâmico: ajuste a regra de associação ou os atributos do usuário."
    if g.is_role_assignable:
        return "Grupo com funções administrativas: remova manualmente (exige administrador)."
    if g.mail_enabled and not g.is_m365:
        return "Lista de distribuição ou grupo habilitado para e-mail: remova no Exchange."
    return ""
