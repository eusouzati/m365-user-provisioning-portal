"""Camada de persistência: SQLite (desenvolvimento local) ou Azure Table Storage."""

from app.config import Settings
from app.storage.base import StorageBackend


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "azure_table":
        from app.storage.azure_table import AzureTableStorage

        return AzureTableStorage(settings.azure_storage_table_endpoint)

    from app.storage.sqlite import SqliteStorage

    return SqliteStorage(settings.sqlite_path)


__all__ = ["StorageBackend", "build_storage"]
