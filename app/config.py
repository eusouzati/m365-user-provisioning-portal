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

    # Autenticação
    # easyauth: App Service Authentication (produção/lab no Azure)
    # dev: usuário simulado — somente desenvolvimento local
    auth_mode: Literal["easyauth", "dev"] = "easyauth"
    dev_user_name: str = "Usuário de Desenvolvimento"
    dev_user_roles: str = ""  # papéis separados por vírgula
    # Definidas pelo próprio App Service (não configurar manualmente)
    website_auth_enabled: bool = False
    website_site_name: str = ""

    # Microsoft Graph
    # msgraph: real (Managed Identity no Azure; "az login" localmente) · fake: dados simulados
    graph_backend: Literal["msgraph", "fake"] = "msgraph"
    graph_cache_seconds: int = Field(default=300, ge=0, le=3600)
    license_mode: Literal["group", "direct"] = "group"
    tap_lifetime_minutes: int = Field(default=480, ge=10, le=43200)
    license_lead_days: int = Field(default=1, ge=0, le=30)
    # Proteção: máximo de contas criadas por dia (DRY_RUN=false)
    provisioning_daily_limit: int = Field(default=20, ge=1, le=1000)

    # Solicitações de novo colaborador
    upn_pattern: str = "{nome}.{ultimo_sobrenome}"
    upn_particles: str = "da,das,de,del,der,di,do,dos,du,e,la,le,van,von,y"
    hire_date_past_days: int = Field(default=30, ge=0, le=365)
    hire_date_future_days: int = Field(default=365, ge=1, le=730)
    # Desligamento: hora local do último dia de trabalho em que a conta é bloqueada
    offboarding_block_hour: int = Field(default=18, ge=0, le=23)
    # LGPD: dias após a conclusão para anonimizar os dados pessoais das solicitações
    # (0 = desativado). Contato do encarregado (DPO) exibido no aviso de privacidade.
    lgpd_retention_days: int = Field(default=0, ge=0, le=3650)
    privacy_contact: str = Field(default="", max_length=200)
    # Grupos que NUNCA podem ser usados em perfis (ex.: grupos dos papéis do portal)
    protected_group_ids: str = ""

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

    @field_validator("upn_pattern")
    @classmethod
    def _upn_pattern_valido(cls, value: str) -> str:
        from app.core.naming import NamingError, validate_pattern

        try:
            return validate_pattern(value)
        except NamingError as exc:
            raise ValueError(f"UPN_PATTERN inválido: {exc}") from exc

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
        if self.auth_mode == "dev":
            if self.is_production:
                raise ValueError("AUTH_MODE=dev é proibido em produção")
            if self.website_site_name:
                raise ValueError("AUTH_MODE=dev é proibido no Azure App Service")
        if self.auth_mode == "easyauth" and not self.azure_tenant_id:
            raise ValueError("AZURE_TENANT_ID é obrigatório quando AUTH_MODE=easyauth")
        if self.is_production and self.graph_backend == "fake":
            raise ValueError("GRAPH_BACKEND=fake é proibido em produção")
        if self.environment == "production" and self.storage_backend == "sqlite":
            raise ValueError("SQLite não é permitido em produção; use STORAGE_BACKEND=azure_table")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def protected_groups(self) -> frozenset[str]:
        return frozenset(
            g.strip().lower() for g in self.protected_group_ids.split(",") if g.strip()
        )

    @property
    def particles(self) -> frozenset[str]:
        return frozenset(p.strip().lower() for p in self.upn_particles.split(",") if p.strip())

    @property
    def dev_roles(self) -> frozenset[str]:
        return frozenset(r.strip() for r in self.dev_user_roles.split(",") if r.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
