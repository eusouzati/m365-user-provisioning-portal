from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.profiles import OnboardingProfile


class SqliteStorage:
    """Armazenamento local para desenvolvimento e testes."""

    name = "sqlite"

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS perfis (id TEXT PRIMARY KEY, dados TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def ping(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()

    def list_profiles(self) -> list[OnboardingProfile]:
        with self._connect() as conn:
            rows = conn.execute("SELECT dados FROM perfis").fetchall()
        profiles = [OnboardingProfile.model_validate_json(r[0]) for r in rows]
        return sorted(profiles, key=lambda p: p.nome.lower())

    def get_profile(self, profile_id: str) -> OnboardingProfile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT dados FROM perfis WHERE id = ?", (profile_id,)).fetchone()
        return OnboardingProfile.model_validate_json(row[0]) if row else None

    def save_profile(self, profile: OnboardingProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO perfis (id, dados) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET dados = excluded.dados",
                (profile.id, profile.model_dump_json()),
            )

    def delete_profile(self, profile_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM perfis WHERE id = ?", (profile_id,))
