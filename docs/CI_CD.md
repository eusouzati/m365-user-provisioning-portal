# CI/CD — GitHub Actions com OIDC

O pipeline publica a aplicação no Azure **sem nenhum segredo no GitHub**: o GitHub Actions apresenta um token OIDC de curta duração, e o Microsoft Entra ID só o aceita porque a identidade de deploy tem uma **credencial federada** que confia exatamente neste repositório **e** neste ambiente do GitHub.

## Fluxo

```text
Pull request / push em outra branch ─► CI (lint, testes + Azurite, pip-audit, Bicep, gitleaks)

Push na main ─► Deploy: CI ─► (se passou) publica no ambiente "lab" ─► confere /health
Manual ─────► Deploy: CI ─► ambiente "lab" ou "production" (production exige aprovação)
```

- O deploy **só acontece se o CI passar** (o workflow `Deploy` chama o `CI`).
- Publica apenas a aplicação (`app/` + `requirements.txt`). **A infraestrutura continua manual** (`Deploy-Infrastructure.ps1`), com pré-visualização e confirmação — mudanças de infraestrutura merecem revisão humana.
- No plano F1 o serviço de publicação às vezes responde 502 logo após reinícios: o workflow tenta de novo uma vez e espera o `/health` por até 10 minutos.
- Enquanto a variável `DEPLOY_LAB_ENABLED` (ou `DEPLOY_PRODUCTION_ENABLED`) não existir, o deploy é **pulado** — forks e quem ainda não configurou continuam só com o CI.

## Configuração (uma vez por ambiente)

```powershell
gh auth login                      # administrador do repositório
az login --tenant <tenant-id>      # Administrador de Aplicativos + Owner no Resource Group
./scripts/New-GitHubDeployIdentity.ps1 -Environment lab -WhatIfOnly   # pré-visualização
./scripts/New-GitHubDeployIdentity.ps1 -Environment lab               # aplica (SIM)
```

O script (idempotente, nunca exclui nada):

| Onde | O que cria/garante |
|---|---|
| Entra ID | App Registration `<prefixo>-github-deploy-<ambiente>` — **sem segredo e sem certificado**, somente este tenant |
| Entra ID | Credencial federada: `repo:<dono>/<repo>:environment:<ambiente>` (emissor `token.actions.githubusercontent.com`) |
| Azure RBAC | Papel **Website Contributor somente no Web App** do ambiente — nada na assinatura, no Storage, no Entra ID ou no Microsoft 365 |
| GitHub | Ambiente `<ambiente>` restrito à **branch main** (production: também **aprovação obrigatória** por você) |
| GitHub | Variáveis do ambiente `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_WEBAPP_NAME` (identificadores, não segredos) |
| GitHub | Variável do repositório `DEPLOY_<AMBIENTE>_ENABLED=true` |

> **Planos do GitHub:** em repositório **público**, ambientes, restrição de branch e aprovação obrigatória são gratuitos. Em repositório **privado**, ambientes exigem Pro/Team/Enterprise e a aprovação obrigatória exige Enterprise. Se o GitHub recusar a aprovação, o script mantém a restrição à `main` e **não habilita produção** — a menos que você rode de novo com `-AllowUnprotectedProduction`.

## Por que é seguro

- **Nada para vazar:** não há client secret, publish profile nem senha no GitHub. O token OIDC vale minutos e só é emitido para jobs do ambiente `<ambiente>` deste repositório — e o ambiente só aceita a `main`, então uma branch qualquer não consegue o token.
- **Escopo mínimo no Azure:** o papel é Website Contributor **somente no Web App** — nada na assinatura, no Storage ou no Entra ID.
- **Seja realista sobre o que isso significa:** publicar código no Web App (ou mudar as configurações dele) equivale a ter os privilégios da própria aplicação, inclusive as permissões do Microsoft Graph da Managed Identity. Por isso: proteja a `main` (pull request + CI obrigatório), limite quem tem permissão de escrita no repositório e mantenha produção com aprovação.
- **Separação lab × produção:** identidades, credenciais federadas e ambientes distintos; a credencial do lab não publica em produção.
- **Revisão:** produção só por disparo manual, com aprovação, a partir da `main`. Com um único mantenedor, a aprovação é sua própria confirmação — em equipe, adicione outros revisores no ambiente `production` do GitHub.
- **Versão conferida:** o `/health` informa a versão e o workflow só conclui quando a versão nova responde.

## Operação

- Publicar agora: **Actions → Deploy → Run workflow** (ou `gh workflow run Deploy -f ambiente=lab`).
- Histórico e logs: aba **Actions** do repositório; o resumo de cada execução mostra a versão publicada.
- Revogar o acesso do GitHub ao Azure: exclua a credencial federada (ou o App Registration `<prefixo>-github-deploy-<ambiente>`) no Entra ID, ou apague a variável `DEPLOY_<AMBIENTE>_ENABLED`.
- Recomendado: em **Settings → Branches**, proteja a `main` exigindo pull request e as verificações `testes`, `bicep` e `segredos` (do workflow CI).
- Endurecimento opcional: trocar Website Contributor por um papel personalizado só com leitura do site e publicação (`Microsoft.Web/sites/read`, `…/publish/Action`, `…/deployments/*`, `…/extensions/*`), impedindo que a identidade de deploy altere configurações de autenticação ou reabilite a autenticação básica.
