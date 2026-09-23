# Configuração do Microsoft Entra ID (login e papéis)

## O que o script cria

`scripts/New-EntraApplication.ps1` é idempotente (pode rodar de novo) e nunca exclui nada.

| Objeto | Nome | Observação |
|---|---|---|
| App Registration | `<prefixo>-portal-<ambiente>` | Somente este tenant; sem Client Secret |
| Enterprise Application | mesmo nome | `appRoleAssignmentRequired = false` (todo o tenant pode entrar; papéis controlam o acesso) |
| Credencial federada (só `-AuthFlow fic`) | `managed-identity-id-<prefixo>-<ambiente>` | Emissor `https://login.microsoftonline.com/<tenant>/v2.0`, sujeito = Object ID da Managed Identity, audiência `api://AzureADTokenExchange` |
| Grupo de segurança | `<PREFIXO>-Solicitantes-RH` | Papel `Provisionamento.Solicitante` |
| Grupo de segurança | `<PREFIXO>-Aprovadores` | Papel `Provisionamento.Aprovador` |
| Grupo de segurança | `<PREFIXO>-Administradores` | Papel `Provisionamento.Administrador` |

Permissão pedida pelo App Registration: apenas `User.Read` (delegada) — para o login.
As permissões de aplicação do Microsoft Graph (criar usuários etc.) serão concedidas à Managed Identity a partir da Sprint 3, uma a uma.

## Fluxo de login (sem segredo nos dois casos)

| `ENTRA_AUTH_FLOW` | Como funciona | Status |
|---|---|---|
| `idtoken` (padrão) | O App Service recebe só o ID token (`form_post`). App Registration com emissão de ID token habilitada. | GA — recomendado |
| `fic` | O App Service troca o código por tokens usando a Managed Identity como credencial federada. | Preview no App Service; falhou no laboratório do projeto (401 no callback) |

O portal não precisa de access token do usuário: as chamadas ao Microsoft Graph usam a Managed Identity do aplicativo. Por isso o fluxo de ID token é suficiente.

## Passo a passo

```powershell
# pré-visualização
pwsh ./scripts/New-EntraApplication.ps1 -Environment lab -WhatIfOnly

# aplicar (e já se incluir nos grupos para testar)
pwsh ./scripts/New-EntraApplication.ps1 -Environment lab -AddMeToGroups Administradores,Solicitantes

# ativar o login no App Service (usa ENTRA_APP_CLIENT_ID gravado no .env)
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab
pwsh ./scripts/Deploy-Application.ps1 -Environment lab
```

Entre com uma conta de **Administrador Global** (ou Administrador de Aplicativos + Administrador de Grupos). O Microsoft Graph PowerShell pedirá consentimento para `Application.ReadWrite.All`, `AppRoleAssignment.ReadWrite.All`, `Group.ReadWrite.All` e `User.Read` — delegadas, usadas só durante a execução do script.

## Gerenciar quem acessa

Adicione ou remova membros dos três grupos pelo Entra admin center. Não é preciso mexer no portal.

- Mudanças de grupo valem no **próximo login** (o papel vem no token). Peça para a pessoa sair e entrar.
- Segregação de funções: evite colocar a mesma pessoa em Solicitantes e Aprovadores em produção (a Sprint 5 também bloqueia aprovar a própria solicitação).
- **Licenciamento**: atribuir *grupos* a aplicativos exige Entra ID P1 ou superior. Sem P1, atribua os papéis diretamente a usuários em *Enterprise Applications → Usuários e grupos*.

## Como a segurança é garantida

1. Login pelo App Service Authentication, restrito ao tenant (`openIdIssuer` do tenant e App Registration `AzureADMyOrg`).
2. O backend só aceita o cabeçalho de identidade se o App Service confirmar que a autenticação está ativa (`WEBSITE_AUTH_ENABLED=True`) — impede falsificação caso o login seja desligado por engano.
3. O backend revalida `tid` (tenant) e `aud` (este aplicativo).
4. Cada rota exige o App Role correspondente; papéis desconhecidos são ignorados.
5. `AUTH_MODE=dev` é recusado em produção e dentro do App Service.

## Testes manuais do checkpoint

| Cenário | Esperado |
|---|---|
| Sem login, abrir o portal | Redireciona para o login Microsoft |
| Usuário do tenant sem grupo | Vê "ainda não possui papel"; `/admin` → 403 |
| Usuário no grupo Administradores | Acessa `/admin`; `/aprovacoes` → 403 |
| Conta de outro tenant | Bloqueada pelo Entra ID (app de tenant único) |
| `/health` sem login | 200 |
| `/api/me` logado | JSON com os papéis |

## Solução de problemas

- **HTTP 401 em `/.auth/login/aad/callback`**: com `fic`, a troca do código falhou. Volte para `idtoken` (`New-EntraApplication.ps1 -AuthFlow idtoken` e `Deploy-Infrastructure.ps1`). O motivo exato aparece em Entra admin center → Monitoramento → Logs de entrada → aba *Entradas de identidade gerenciada* / *Entradas de entidade de serviço*.
- **AADSTS700213 / erro de credencial federada** no login: confira se a credencial federada existe no App Registration com o *Object (principal) ID* da Managed Identity e se o App Setting `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID` contém o *Client ID* da Managed Identity. Esse recurso do App Service está em *preview*; como alternativa temporária é possível usar um Client Secret guardado no Key Vault (não recomendado).
- **Papel não aparece**: saia (`/.auth/logout`) e entre novamente; confira `/api/me`.
- **"autenticação do App Service está desativada" nos logs**: rode `Deploy-Infrastructure.ps1` depois de gravar `ENTRA_APP_CLIENT_ID` no `.env`.
