from __future__ import annotations


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

    def ping(self) -> None:
        pages = self._client.list_tables(results_per_page=1).by_page()
        next(pages, None)
