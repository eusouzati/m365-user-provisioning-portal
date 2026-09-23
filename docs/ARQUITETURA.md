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
