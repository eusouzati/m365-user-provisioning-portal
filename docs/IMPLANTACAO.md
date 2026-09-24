# Implantação no seu tenant

## 1. Pré-requisitos

- Windows PowerShell 5.1 ou PowerShell 7+, Azure CLI (`az upgrade`), Bicep (`az bicep install`), Python 3.11+, Git, GitHub CLI.
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

## 5. Habilitar a criação real de contas

Por padrão o portal roda com `DRY_RUN=true` (nada é alterado no Microsoft 365). Para criar contas:

1. Conceda as permissões de escrita: `pwsh ./scripts/Set-GraphPermissions.ps1 -Environment lab -Nivel criacao`
2. No `.env`, defina `DRY_RUN=false` (e, se quiser, `PROVISIONING_DAILY_LIMIT`).
3. Aplique: `pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab` (o script avisa que o modo real será ativado).
4. Aprove uma solicitação de teste (ou, numa já aprovada, use **Criar conta no Microsoft 365** como Administrador).
5. Confira no Entra admin center: usuário **desativado**, sem licença, com gestor e grupos.

Para voltar ao modo seguro, defina `DRY_RUN=true` e rode `Deploy-Infrastructure.ps1` novamente.

## 6. Ciclo de vida (licença D-1, ativação D0) e acesso inicial

```powershell
pwsh ./scripts/New-EntraApplication.ps1 -Environment lab      # papel Agendador + api://<client-id>
pwsh ./scripts/Set-GraphPermissions.ps1 -Environment lab -Nivel ciclo-de-vida
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab     # cria a Logic App (agendador)
pwsh ./scripts/Deploy-Application.ps1 -Environment lab
```

Requisitos no tenant: política de **Temporary Access Pass** habilitada (Entra admin center → Métodos de autenticação) e, com `LICENSE_MODE=group`, um grupo de segurança com a licença atribuída, selecionado no perfil.

Teste: em **Administração → Todas as solicitações**, clique em **Executar ciclo de vida agora**. No dia da admissão, o gestor acessa **Minha equipe** e gera o acesso inicial.

## 7. Desligamento

```powershell
pwsh ./scripts/Set-GraphPermissions.ps1 -Environment lab -Nivel desligamento   # User.RevokeSessions.All
az webapp restart -g rg-<prefixo>-<ambiente> -n <web-app>                     # renova o token da identidade
pwsh ./scripts/Deploy-Application.ps1 -Environment lab
```

O agendador (a mesma Logic App) executa os desligamentos no horário do bloqueio (`OFFBOARDING_BLOCK_HOUR`, padrão 18h do último dia). Detalhes em [DESLIGAMENTO.md](DESLIGAMENTO.md).

## 8. Solução de problemas

- `/health/ready` com 503 logo após criar a infraestrutura: as permissões RBAC da Managed Identity podem levar até ~10 minutos para propagar.
- Logs: `az webapp log tail -g rg-<prefixo>-lab -n <webAppName>`.
- Agendador sem efeito: veja o histórico de execuções da Logic App `logic-<prefixo>-<ambiente>` no portal do Azure. 401/403 → rode `New-EntraApplication.ps1` de novo (papel Agendador e `api://<client-id>`) e aguarde alguns minutos.
- Nome de Storage/Web App já em uso: altere `RESOURCE_PREFIX`.
- `SubscriptionIsOverQuotaForSku` (comum em assinaturas **Free Trial**): a assinatura tem cota 0 de App Service para o plano/região. Opções:
  1. testar outra região: `-Location eastus2` (o what-if não cria nada);
  2. testar outro plano: `-AppServiceSku B1` (pago);
  3. solicitar cota: portal do Azure → **Cotas** → **App Service** → região → plano → *Solicitar aumento*;
  4. converter a assinatura para pay-as-you-go (o F1 continua gratuito).
