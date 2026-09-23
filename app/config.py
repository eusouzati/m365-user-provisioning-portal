"""Configuração da aplicação.

Todos os valores vêm de variáveis de ambiente (ou de um arquivo ``.env`` local,
que nunca deve ser versionado). Nenhum dado de tenant fica no código.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Aplicação
    app_name: str = "Portal de Provisionamento M365"
    environment: Literal["lab", "production"] = "lab"
    dry_run: bool = True
    enable_api_docs: bool = False
    log_level: str = "INFO"

    # Tenant (preenchido por quem implanta)
    azure_tenant_id: str = ""
    entra_app_client_id: str = ""
    m365_default_domain: str = ""
    m365_default_usage_location: str = Field(default="BR", min_length=2, max_length=2)
    timezone: str = "America/Sao_Paulo"

    # Armazenamento
    storage_backend: Literal["sqlite", "azure_table"] = "sqlite"
    sqlite_path: str = "data/m365up.db"
    azure_storage_table_endpoint: str = ""

    # Observabilidade
    applicationinsights_connection_string: str = ""

    @field_validator("m365_default_usage_location")
    @classmethod
    def _usage_location_upper(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("M365_DEFAULT_USAGE_LOCATION deve ser um código ISO de 2 letras")
        return value.upper()

    @field_validator("timezone")
    @classmethod
    def _timezone_valido(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TIMEZONE inválido: {value}") from exc
        return value

    @model_validator(mode="after")
    def _regras_de_ambiente(self) -> Settings:
        if self.storage_backend == "azure_table" and not self.azure_storage_table_endpoint:
            raise ValueError(
                "AZURE_STORAGE_TABLE_ENDPOINT é obrigatório quando STORAGE_BACKEND=azure_table"
            )
        if self.environment == "production" and self.storage_backend == "sqlite":
            raise ValueError("SQLite não é permitido em produção; use STORAGE_BACKEND=azure_table")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
