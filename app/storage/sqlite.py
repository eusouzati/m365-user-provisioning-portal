from __future__ import annotations

import sqlite3
from pathlib import Path


class SqliteStorage:
    """Armazenamento local para desenvolvimento e testes."""

    name = "sqlite"

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def ping(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
