from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_padroes_seguros():
    s = Settings(_env_file=None)
    assert s.environment == "lab"
    assert s.dry_run is True
    assert s.storage_backend == "sqlite"


def test_usage_location_normalizado():
    s = Settings(_env_file=None, m365_default_usage_location="br")
    assert s.m365_default_usage_location == "BR"


@pytest.mark.parametrize("valor", ["B", "BRA", "1A"])
def test_usage_location_invalido(valor):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, m365_default_usage_location=valor)


def test_timezone_invalido():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, timezone="Marte/Olimpo")


def test_sqlite_proibido_em_producao():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")


def test_azure_table_exige_endpoint():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_backend="azure_table")
