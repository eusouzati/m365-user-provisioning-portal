from __future__ import annotations

import time
from datetime import date

from app.core.profiles import OnboardingProfile
from app.core.workflow import REQUEST_ID_RE, ProvisioningRequest, format_request_id
from app.storage.errors import ConcurrencyError, DuplicateRequestError

PROFILES_TABLE = "perfis"
PROFILES_PARTITION = "perfil"
REQUESTS_TABLE = "solicitacoes"
PK_REQUEST, PK_COUNTER, PK_IDEM = "req", "contador", "idem"


def _odata(value: str) -> str:
    return value.replace("'", "''")


class AzureTableStorage:
    """Azure Table Storage acessado via Managed Identity (sem chave de acesso).

    ``DefaultAzureCredential`` usa a variável ``AZURE_CLIENT_ID`` para escolher a
    Managed Identity atribuída pelo usuário no App Service.
    """

    name = "azure_table"

    def __init__(self, endpoint: str = "", *, connection_string: str = "") -> None:
        from azure.data.tables import TableServiceClient

        if connection_string:  # somente testes (Azurite)
            self._client = TableServiceClient.from_connection_string(connection_string)
        else:
            from azure.identity import DefaultAzureCredential

            self._client = TableServiceClient(
                endpoint=endpoint, credential=DefaultAzureCredential()
            )
        self._tables: dict[str, object] = {}

    def _table(self, name: str):
        if name not in self._tables:
            self._tables[name] = self._client.create_table_if_not_exists(name)
        return self._tables[name]

    def ping(self) -> None:
        pages = self._client.list_tables(results_per_page=1).by_page()
        next(pages, None)

    # --------------------------------------------------------------- perfis
    def list_profiles(self) -> list[OnboardingProfile]:
        rows = self._table(PROFILES_TABLE).query_entities(f"PartitionKey eq '{PROFILES_PARTITION}'")
        profiles = [OnboardingProfile.model_validate_json(r["dados"]) for r in rows]
        return sorted(profiles, key=lambda p: p.nome.lower())

    def get_profile(self, profile_id: str) -> OnboardingProfile | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            row = self._table(PROFILES_TABLE).get_entity(PROFILES_PARTITION, profile_id)
        except ResourceNotFoundError:
            return None
        return OnboardingProfile.model_validate_json(row["dados"])

    def save_profile(self, profile: OnboardingProfile) -> None:
        self._table(PROFILES_TABLE).upsert_entity(
            {
                "PartitionKey": PROFILES_PARTITION,
                "RowKey": profile.id,
                "nome": profile.nome,
                "dados": profile.model_dump_json(),
            }
        )

    def delete_profile(self, profile_id: str) -> None:
        self._table(PROFILES_TABLE).delete_entity(PROFILES_PARTITION, profile_id)

    # ---------------------------------------------------------- solicitações
    def next_request_id(self, day: date) -> str:
        from azure.core import MatchConditions
        from azure.core.exceptions import (
            ResourceExistsError,
            ResourceModifiedError,
            ResourceNotFoundError,
        )
        from azure.data.tables import UpdateMode

        table = self._table(REQUESTS_TABLE)
        key = day.strftime("%Y%m%d")
        for attempt in range(20):
            try:
                ent = table.get_entity(PK_COUNTER, key)
            except ResourceNotFoundError:
                try:
                    table.create_entity({"PartitionKey": PK_COUNTER, "RowKey": key, "n": 1})
                    return format_request_id(day, 1)
                except ResourceExistsError:
                    continue
            n = int(ent["n"]) + 1
            ent["n"] = n
            try:
                table.update_entity(
                    ent,
                    mode=UpdateMode.REPLACE,
                    etag=ent.metadata["etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
                return format_request_id(day, n)
            except ResourceModifiedError:
                time.sleep(0.05 * (attempt + 1))
        raise ConcurrencyError("contador de solicitações")

    def _entity(self, req: ProvisioningRequest) -> dict:
        return {
            "PartitionKey": PK_REQUEST,
            "RowKey": req.id,
            "status": req.status,
            "solicitante": req.solicitante.oid.lower(),
            "criado_em": req.criado_em.isoformat(),
            "versao": req.versao,
            "dados": req.model_dump_json(),
        }

    def create_request(self, req: ProvisioningRequest) -> None:
        from azure.core.exceptions import ResourceExistsError

        table = self._table(REQUESTS_TABLE)
        for _ in range(2):
            try:
                table.create_entity(
                    {"PartitionKey": PK_IDEM, "RowKey": req.idempotency_key, "request_id": req.id}
                )
                break
            except ResourceExistsError:
                existing = table.get_entity(PK_IDEM, req.idempotency_key)["request_id"]
                if self.get_request(existing):
                    raise DuplicateRequestError(existing) from None
                # chave órfã (falha entre as duas gravações): libera e tenta de novo
                table.delete_entity(PK_IDEM, req.idempotency_key)
        table.create_entity(self._entity(req))

    def get_request(self, request_id: str) -> ProvisioningRequest | None:
        from azure.core.exceptions import ResourceNotFoundError

        if not REQUEST_ID_RE.match(request_id):
            return None
        try:
            ent = self._table(REQUESTS_TABLE).get_entity(PK_REQUEST, request_id)
        except ResourceNotFoundError:
            return None
        return ProvisioningRequest.model_validate_json(ent["dados"])

    def update_request(self, req: ProvisioningRequest) -> ProvisioningRequest:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        from azure.data.tables import UpdateMode

        table = self._table(REQUESTS_TABLE)
        try:
            current = table.get_entity(PK_REQUEST, req.id)
        except ResourceNotFoundError as exc:
            raise ConcurrencyError(req.id) from exc
        if int(current["versao"]) != req.versao:
            raise ConcurrencyError(req.id)
        novo = req.model_copy(update={"versao": req.versao + 1})
        try:
            table.update_entity(
                self._entity(novo),
                mode=UpdateMode.REPLACE,
                etag=current.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except ResourceModifiedError as exc:
            raise ConcurrencyError(req.id) from exc
        return novo

    def list_requests(
        self, *, status: str | None = None, solicitante_oid: str | None = None, limit: int = 200
    ) -> list[ProvisioningRequest]:
        filtro = f"PartitionKey eq '{PK_REQUEST}'"
        if status:
            filtro += f" and status eq '{_odata(status)}'"
        if solicitante_oid:
            filtro += f" and solicitante eq '{_odata(solicitante_oid.lower())}'"
        rows = self._table(REQUESTS_TABLE).query_entities(
            filtro, select=["dados", "criado_em", "RowKey"]
        )
        itens = sorted(rows, key=lambda r: (r["criado_em"], r["RowKey"]), reverse=True)[:limit]
        return [ProvisioningRequest.model_validate_json(r["dados"]) for r in itens]
