"""Camada de persistência: SQLite (desenvolvimento local) ou Azure Table Storage."""

from app.config import Settings
from app.storage.base import StorageBackend


def build_storage(settings: Settings) -> StorageBackend:
    """Armazenamento com auditoria automática das gravações."""
    from app.storage.auditing import AuditingStorage

    if settings.storage_backend == "azure_table":
        from app.storage.azure_table import AzureTableStorage

        return AuditingStorage(AzureTableStorage(settings.azure_storage_table_endpoint))

    from app.storage.sqlite import SqliteStorage

    return AuditingStorage(SqliteStorage(settings.sqlite_path))


__all__ = ["StorageBackend", "build_storage"]
