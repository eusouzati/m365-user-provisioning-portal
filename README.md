# Portal de Provisionamento de Usuários Microsoft 365

Portal **open source** (licença MIT) para automatizar a entrada e a saída de colaboradores no **Microsoft 365 / Entra ID** a partir das solicitações do RH — com aprovação, conta criada desativada, licença perto da admissão, acesso inicial via **Temporary Access Pass** e auditoria.

Cada organização implanta o portal **no próprio tenant e na própria assinatura Azure**. Nenhum dado de tenant fica neste repositório.

> **Status:** em desenvolvimento (v0.2 — Sprint 2: login Entra ID e papéis). Ainda não cria usuários.

## Como funciona

```text
RH solicita → Aprovação → Conta criada DESATIVADA e sem licença
→ D-1: entra no grupo de licença → D0: conta ativada + gestor gera o TAP
→ Colaborador registra MFA no primeiro acesso → tudo auditado
```

Desligamento: desativar conta, revogar sessões, remover grupos e, após N dias, a licença. Nada é excluído automaticamente.

## Requisitos

| Item | Mínimo |
|---|---|
| Microsoft Entra ID | Free (núcleo) · P1 recomendado (licenciamento por grupo) · Governance opcional (Lifecycle Workflows) |
| Tenant | Somente nuvem (sem sincronização com AD local) |
| Azure | Qualquer assinatura (inclusive Free Trial para laboratório) |
| Ferramentas | Windows PowerShell 5.1 ou PowerShell 7+, Azure CLI + Bicep, Python 3.11+, Git, GitHub CLI |

## Início rápido (laboratório)

```powershell
git clone https://github.com/<voce>/m365-user-provisioning-portal.git
cd m365-user-provisioning-portal
Copy-Item .env.example .env      # preencha AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, M365_DEFAULT_DOMAIN

pwsh ./scripts/Test-Prerequisites.ps1 -TenantId <seu-tenant-id>   # somente leitura
az login --tenant <seu-tenant-id>
az bicep install

pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab -WhatIfOnly   # pré-visualização
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab               # cria (pede confirmação)
pwsh ./scripts/Deploy-Application.ps1 -Environment lab                  # publica e testa /health

pwsh ./scripts/New-EntraApplication.ps1 -Environment lab -AddMeToGroups Administradores   # login + papéis
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab               # ativa o login no App Service
```

Guia completo: [docs/IMPLANTACAO.md](docs/IMPLANTACAO.md) · Login e papéis: [docs/CONFIGURACAO_ENTRA.md](docs/CONFIGURACAO_ENTRA.md).

## Desenvolvimento local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
uvicorn app.main:create_app --factory --reload   # http://localhost:8000 (AUTH_MODE=dev)
pytest
ruff check .
```

## Estrutura

```text
app/        FastAPI (portal + API)
functions/  Agendador de ciclo de vida (Sprint 7)
infra/      Bicep
scripts/    PowerShell de apoio
docs/       Documentação
tests/      Testes
```

## Segurança

- Sem Client Secret: Microsoft Graph via **Managed Identity**, deploy via **GitHub OIDC**.
- O RH nunca vê credenciais; senhas e TAP nunca são registrados.
- Relate vulnerabilidades conforme [SECURITY.md](SECURITY.md).

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md) e o [Código de Conduta](CODE_OF_CONDUCT.md).

## Licença

[MIT](LICENSE)
