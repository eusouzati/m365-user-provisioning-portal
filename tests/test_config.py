from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

T = "11111111-1111-1111-1111-111111111111"


def test_padroes_seguros():
    s = Settings(_env_file=None, azure_tenant_id=T)
    assert s.environment == "lab"
    assert s.dry_run is True
    assert s.storage_backend == "sqlite"
    assert s.auth_mode == "easyauth"


def test_easyauth_exige_tenant():
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_dev_proibido_em_producao():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            azure_tenant_id=T,
            auth_mode="dev",
            environment="production",
            storage_backend="azure_table",
            azure_storage_table_endpoint="https://x.table.core.windows.net",
        )


def test_dev_proibido_no_app_service():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_mode="dev", website_site_name="app-x")


def test_dev_roles():
    s = Settings(_env_file=None, auth_mode="dev", dev_user_roles=" A, B ,,")
    assert s.dev_roles == frozenset({"A", "B"})


def test_usage_location_normalizado():
    s = Settings(_env_file=None, azure_tenant_id=T, m365_default_usage_location="br")
    assert s.m365_default_usage_location == "BR"


@pytest.mark.parametrize("valor", ["B", "BRA", "1A"])
def test_usage_location_invalido(valor):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_tenant_id=T, m365_default_usage_location=valor)


def test_timezone_invalido():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_tenant_id=T, timezone="Marte/Olimpo")


def test_sqlite_proibido_em_producao():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_tenant_id=T, environment="production")


def test_azure_table_exige_endpoint():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, azure_tenant_id=T, storage_backend="azure_table")
