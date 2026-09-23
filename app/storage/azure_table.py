from __future__ import annotations

from app.core.profiles import OnboardingProfile

PROFILES_TABLE = "perfis"
PROFILES_PARTITION = "perfil"


class AzureTableStorage:
    """Azure Table Storage acessado via Managed Identity (sem chave de acesso).

    ``DefaultAzureCredential`` usa a variável ``AZURE_CLIENT_ID`` para escolher a
    Managed Identity atribuída pelo usuário no App Service.
    """

    name = "azure_table"

    def __init__(self, endpoint: str) -> None:
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        self._client = TableServiceClient(endpoint=endpoint, credential=DefaultAzureCredential())
        self._profiles = None

    def _profiles_table(self):
        if self._profiles is None:
            self._profiles = self._client.create_table_if_not_exists(PROFILES_TABLE)
        return self._profiles

    def ping(self) -> None:
        pages = self._client.list_tables(results_per_page=1).by_page()
        next(pages, None)

    def list_profiles(self) -> list[OnboardingProfile]:
        rows = self._profiles_table().query_entities(f"PartitionKey eq '{PROFILES_PARTITION}'")
        profiles = [OnboardingProfile.model_validate_json(r["dados"]) for r in rows]
        return sorted(profiles, key=lambda p: p.nome.lower())

    def get_profile(self, profile_id: str) -> OnboardingProfile | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            row = self._profiles_table().get_entity(PROFILES_PARTITION, profile_id)
        except ResourceNotFoundError:
            return None
        return OnboardingProfile.model_validate_json(row["dados"])

    def save_profile(self, profile: OnboardingProfile) -> None:
        self._profiles_table().upsert_entity(
            {
                "PartitionKey": PROFILES_PARTITION,
                "RowKey": profile.id,
                "nome": profile.nome,
                "dados": profile.model_dump_json(),
            }
        )

    def delete_profile(self, profile_id: str) -> None:
        self._profiles_table().delete_entity(PROFILES_PARTITION, profile_id)
