from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from app.core.profiles import OnboardingProfile
from app.core.workflow import ProvisioningRequest, format_request_id
from app.storage.errors import ConcurrencyError, DuplicateRequestError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS perfis (id TEXT PRIMARY KEY, dados TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contador (dia TEXT PRIMARY KEY, n INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS solicitacoes (
    id TEXT PRIMARY KEY,
    idem TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    solicitante TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    versao INTEGER NOT NULL,
    dados TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_solic_status ON solicitacoes(status);
CREATE INDEX IF NOT EXISTS ix_solic_solicitante ON solicitacoes(solicitante);
"""


class SqliteStorage:
    """Armazenamento local para desenvolvimento e testes."""

    name = "sqlite"

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10, isolation_level=None)

    def ping(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()

    # --------------------------------------------------------------- perfis
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

    # ---------------------------------------------------------- solicitações
    def next_request_id(self, day: date) -> str:
        key = day.strftime("%Y%m%d")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO contador (dia, n) VALUES (?, 1) "
                "ON CONFLICT(dia) DO UPDATE SET n = n + 1",
                (key,),
            )
            n = conn.execute("SELECT n FROM contador WHERE dia = ?", (key,)).fetchone()[0]
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return format_request_id(day, n)

    def create_request(self, req: ProvisioningRequest) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM solicitacoes WHERE idem = ?", (req.idempotency_key,)
            ).fetchone()
            if existing:
                raise DuplicateRequestError(existing[0])
            try:
                conn.execute(
                    "INSERT INTO solicitacoes (id, idem, status, solicitante, criado_em, versao, "
                    "dados) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        req.id,
                        req.idempotency_key,
                        req.status,
                        req.solicitante.oid.lower(),
                        req.criado_em.isoformat(),
                        req.versao,
                        req.model_dump_json(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                row = conn.execute(
                    "SELECT id FROM solicitacoes WHERE idem = ?", (req.idempotency_key,)
                ).fetchone()
                if row:
                    raise DuplicateRequestError(row[0]) from exc
                raise

    def get_request(self, request_id: str) -> ProvisioningRequest | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT dados FROM solicitacoes WHERE id = ?", (request_id,)
            ).fetchone()
        return ProvisioningRequest.model_validate_json(row[0]) if row else None

    def update_request(self, req: ProvisioningRequest) -> ProvisioningRequest:
        expected = req.versao
        novo = req.model_copy(update={"versao": expected + 1})
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE solicitacoes SET status = ?, versao = ?, dados = ? "
                "WHERE id = ? AND versao = ?",
                (novo.status, novo.versao, novo.model_dump_json(), novo.id, expected),
            )
            if cur.rowcount != 1:
                raise ConcurrencyError(req.id)
        return novo

    def list_requests(
        self, *, status: str | None = None, solicitante_oid: str | None = None, limit: int = 200
    ) -> list[ProvisioningRequest]:
        sql, args = "SELECT dados FROM solicitacoes WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if solicitante_oid:
            sql += " AND solicitante = ?"
            args.append(solicitante_oid.lower())
        sql += " ORDER BY criado_em DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [ProvisioningRequest.model_validate_json(r[0]) for r in rows]
