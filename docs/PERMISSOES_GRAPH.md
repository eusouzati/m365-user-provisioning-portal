# Permissões do Microsoft Graph

O portal usa **duas identidades diferentes**:

| Identidade | Para quê | Permissões |
|---|---|---|
| App Registration `<prefixo>-portal-<ambiente>` | Login dos usuários (App Service Authentication) | `User.Read` (delegada) |
| Managed Identity `id-<prefixo>-<ambiente>` | Todas as chamadas do portal ao Microsoft Graph | Permissões de **aplicação**, listadas abaixo |

As permissões de aplicação são concedidas por nível, com `scripts/Set-GraphPermissions.ps1` (pré-visualização + confirmação `SIM`). O script nunca remove permissões.

## Nível `leitura` (Sprint 3)

| Permissão | Uso no portal |
|---|---|
| `User.Read.All` | Buscar gestores; verificar se UPN, e-mail, `mailNickname` ou `proxyAddresses` já existem |
| `Group.Read.All` | Listar grupos elegíveis para perfis e grupos com licença atribuída |
| `Organization.Read.All` | Dados da organização e licenças do tenant (`subscribedSkus`) |
| `Domain.Read.All` | Domínios verificados |
| `Policy.Read.AuthenticationMethod` | Ler a política de Temporary Access Pass |

Com este nível, o portal **não consegue alterar nada** no Microsoft 365. Além disso, o `GraphService` bloqueia no código qualquer requisição diferente de `GET` (`ReadOnlyViolationError`).

## Nível `criacao` (Sprint 6) — inclui `leitura`

```powershell
./scripts/Set-GraphPermissions.ps1 -Environment lab -Nivel criacao
```

| Permissão | Uso no portal |
|---|---|
| `User.ReadWrite.All` | Criar a conta (desativada), definir propriedades e gestor |
| `User-LifeCycleInfo.ReadWrite.All` | `employeeHireDate` (e, na Sprint 8, `employeeLeaveDateTime`) |
| `GroupMember.ReadWrite.All` | Adicionar aos grupos de acesso do perfil |

Proteções adicionais no código: escrita só existe com `DRY_RUN=false` (`MsGraphWriter`); grupos revalidados antes de cada inclusão; grupos com funções administrativas são recusados (e o Graph também os bloqueia sem `RoleManagement.*`); limite diário de contas (`PROVISIONING_DAILY_LIMIT`).

## Próximos níveis (planejados)

| Nível | Sprint | Permissões | Motivo |
|---|---|---|---|
| `ciclo-de-vida` | 7 | `UserAuthenticationMethod.ReadWrite.All` (+ `LicenseAssignment.ReadWrite.All` só com `LICENSE_MODE=direct`) | Gerar TAP; licença direta |
| `desligamento` | 8 | `User.RevokeSessions.All` | Revogar sessões |

## Riscos e mitigação

- Permissões de aplicação valem para o tenant inteiro. Mitigação: allowlist de grupos validada no backend, grupos protegidos (`PROTECTED_GROUP_IDS`), bloqueio de grupos com funções administrativas e dinâmicos, auditoria (Sprint 9) e Managed Identity sem segredo.
- Revise periodicamente: Entra admin center → Aplicativos empresariais → filtro "Identidades gerenciadas" → `id-<prefixo>-<ambiente>` → Permissões.

## Desenvolvimento local

Com `GRAPH_BACKEND=fake` (padrão do `.env.example`) o portal usa dados simulados, sem rede. Com `GRAPH_BACKEND=msgraph` localmente, o `DefaultAzureCredential` usa o seu `az login` — as permissões passam a ser as **suas** (delegadas), não as da Managed Identity.
