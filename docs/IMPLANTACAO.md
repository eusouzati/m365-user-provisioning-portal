# Implantação no seu tenant

## 1. Pré-requisitos

- PowerShell 7+, Azure CLI (`az upgrade`), Bicep (`az bicep install`), Python 3.11+, Git, GitHub CLI.
- Conta com **Owner** na assinatura Azure (necessário para as atribuições de RBAC da Managed Identity).
- Tenant Entra ID somente nuvem.

## 2. Configuração

```powershell
Copy-Item .env.example .env
```

Preencha `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_LOCATION`, `RESOURCE_PREFIX`, `M365_DEFAULT_DOMAIN`.

Valide (somente leitura):

```powershell
pwsh ./scripts/Test-Prerequisites.ps1 -TenantId <tenant-id>
```

## 3. Infraestrutura

```powershell
az login --tenant <tenant-id>
az account set --subscription <subscription-id>
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab -WhatIfOnly
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab
```

O script confere tenant e subscription, mostra o *what-if* e só aplica após você digitar `SIM`. As saídas ficam em `infra-outputs.lab.json` (ignorado pelo Git).

### Custo estimado (lab)

| Recurso | Plano | Custo |
|---|---|---|
| App Service | F1 | Gratuito (cota diária de CPU, sem Always On) |
| Storage Account | Standard LRS | Centavos/mês |
| Log Analytics + App Insights | Pay-as-you-go, limite diário de 1 GB, amostragem 50% | Normalmente dentro da franquia gratuita mensal |
| Managed Identity | — | Gratuito |

Produção: use `-AppServiceSku B1` ou superior.

## 4. Aplicação

```powershell
pwsh ./scripts/Deploy-Application.ps1 -Environment lab
```

O primeiro deploy compila as dependências no App Service e pode levar alguns minutos no plano F1. Ao final, o script valida `/health` e `/health/ready`.

## 5. Solução de problemas

- `/health/ready` com 503 logo após criar a infraestrutura: as permissões RBAC da Managed Identity podem levar até ~10 minutos para propagar.
- Logs: `az webapp log tail -g rg-<prefixo>-lab -n <webAppName>`.
- Nome de Storage/Web App já em uso: altere `RESOURCE_PREFIX`.
