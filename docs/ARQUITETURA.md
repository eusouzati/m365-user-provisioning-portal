# Arquitetura

> Documento vivo — cresce a cada Sprint.

## Visão geral

```text
Navegador (RH / Aprovador / Gestor)
        │  HTTPS
        ▼
Azure App Service (Linux, Python/FastAPI)  ──►  Azure Table Storage (solicitações, auditoria)
        │  Managed Identity (sem segredos)            ▲
        ▼                                             │
Microsoft Graph (Entra ID / M365)   Azure Functions (agendador D-1 / D0 / desligamento) — Sprint 7
        │
Application Insights / Log Analytics (sem dados sensíveis)
```

## Decisões

| Decisão | Motivo |
|---|---|
| Managed Identity atribuída pelo usuário | Sem Client Secret; a mesma identidade serve App Service e Functions |
| Storage com `allowSharedKeyAccess=false` | Acesso apenas via Entra ID/RBAC |
| Autenticação básica (FTP/SCM) desabilitada | Deploy usa token do Entra ID |
| Nomes globais com sufixo `uniqueString` | Evita colisão entre organizações que usam o projeto |
| App Service F1 no lab | Custo zero; produção usa B1+ (Always On) |
| SQLite local / Azure Table na nuvem | Desenvolvimento sem Azure; custo mínimo em produção |
| Tenant somente nuvem | Contas criadas direto no Entra ID via Graph |

## Recursos (por ambiente)

| Recurso | Nome |
|---|---|
| Resource Group | `rg-<prefixo>-<ambiente>` |
| Managed Identity | `id-<prefixo>-<ambiente>` |
| App Service Plan | `asp-<prefixo>-<ambiente>` |
| Web App | `app-<prefixo>-<ambiente>-<sufixo>` |
| Storage Account | `st<prefixo><lab\|prd><sufixo>` (tabelas `solicitacoes`, `auditoria`; fila `tarefas`) |
| Log Analytics | `log-<prefixo>-<ambiente>` |
| Application Insights | `appi-<prefixo>-<ambiente>` |

## Autenticação e autorização (Sprint 2)

```text
Navegador ──► App Service Authentication (Easy Auth)
                 │  login Entra ID (somente este tenant)
                 │  sem Client Secret: Managed Identity como credencial federada
                 ▼
             FastAPI recebe X-MS-CLIENT-PRINCIPAL
                 │  confia no cabeçalho só se WEBSITE_AUTH_ENABLED=True
                 │  valida tenant (tid) e audiência (aud)
                 ▼
             App Roles do token ──► Solicitante / Aprovador / Administrador
```

- **Autenticação** (quem é): Easy Auth + validação de tenant/audiência no backend.
- **Autorização** (o que pode): App Roles, verificados em cada rota do backend. O menu da interface apenas reflete os papéis — não é controle de acesso.
- Qualquer usuário do tenant pode entrar (os gestores precisarão gerar o TAP na Sprint 7), mas sem papel só vê a página inicial.
- `/health` e `/health/ready` são públicos (excluídos do login).
