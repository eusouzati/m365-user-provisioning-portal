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
Microsoft Graph (Entra ID / M365)   Logic App (agendador de hora em hora: D-1 / D0 / desligamento)
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
| Storage Account | `st<prefixo><lab\|prd><sufixo>` (tabelas `solicitacoes`, `auditoria`, `perfis`, `estado`; fila `tarefas`) |
| Log Analytics | `log-<prefixo>-<ambiente>` |
| Application Insights | `appi-<prefixo>-<ambiente>` |

## Autenticação e autorização (Sprint 2)

```text
Navegador ──► App Service Authentication (Easy Auth)
                 │  login Entra ID (somente este tenant)
                 │  sem Client Secret: fluxo de ID token (padrão) ou Managed Identity (preview)
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

## Microsoft Graph (Sprint 3)

- `app/graph/service.py` é a **única** camada que fala com o Graph. Nesta versão só executa `GET`.
- Leituras do tenant ficam em cache por `GRAPH_CACHE_SECONDS` (padrão 300 s); o botão "Atualizar" força nova leitura.
- Perfis de onboarding ficam no Azure Table `perfis`. Ao salvar, os IDs recebidos do navegador são **revalidados contra o tenant** (grupo existe, é de segurança, não é dinâmico, não tem funções administrativas, não é grupo de papel do portal).
- Formulários usam proteção CSRF (cookie HttpOnly/SameSite=Strict + campo oculto + verificação de `Origin`).

## Solicitação de novo colaborador (Sprint 4)

```text
Formulário (RH) ──► POST /solicitacoes/revisar ──► tela de revisão
                         │ valida campos (limites do Graph)
                         │ valida perfil ativo e tipo, gestor ativo, matrícula única, datas
                         │ gera UPN e resolve colisões consultando o diretório
                         ▼
                   POST /solicitacoes/enviar ──► recalcula TUDO de novo no servidor
                                                 (Sprint 4: simulação — nada gravado)
```

Regras de nome: [REGRAS_DE_NOME.md](REGRAS_DE_NOME.md).

## Solicitações e aprovação (Sprint 5)

```text
enviada ──► aprovada ──► (Sprint 6+) conta_criada ► licenciada ► ativa
   │   └──► rejeitada (comentário obrigatório)
   └──────► cancelada (solicitante ou administrador)
```

- **Request ID** `REQ-AAAAMMDD-NNNN`, sequencial por dia (fuso `TIMEZONE`), gerado de forma atômica (transação no SQLite; ETag no Azure Table).
- **Idempotência**: a tela de revisão gera uma chave única; reenvios e duplo clique com a mesma chave levam à solicitação já criada. O botão também é desabilitado no navegador.
- **Segregação**: quem solicitou não aprova nem rejeita a própria solicitação — mesmo tendo os dois papéis.
- **Revalidação na aprovação**: perfil, gestor, matrícula e UPN são conferidos de novo no tenant; se o UPN ficou indisponível, é recalculado e a mudança fica no histórico.
- **Reservas**: UPNs e matrículas de solicitações em andamento não podem ser reutilizados por outra solicitação.
- **Concorrência**: gravações usam versão/ETag; decisões simultâneas não se sobrescrevem.
- **Visibilidade**: o solicitante vê só as próprias solicitações; Aprovadores e Administradores veem todas.

Armazenamento (Azure Table `solicitacoes`): `PartitionKey=req` (solicitação), `contador` (sequência diária) e `idem` (chaves de idempotência).

## Provisionamento (Sprint 6)

```text
Aprovação ──► UserProvisioningService
               1. criar usuário (accountEnabled=false, sem licença, senha aleatória descartada)
               2. definir gestor
               3. adicionar aos grupos de acesso (revalidados no tenant)
             ──► conta_criada   (todas as etapas ok)
             ──► falha_parcial  (etapas com falha ficam registradas; Administrador reprocessa)
```

- `DRY_RUN=true`: o `DryRunWriter` não chama o Graph; as etapas ficam "Simulada".
- Reprocessar executa só etapas pendentes/falhas. Se o usuário já existe com a mesma matrícula (ex.: timeout depois da criação), ele é reaproveitado; se o UPN pertence a outra pessoa, a etapa falha.
- Nunca exclui usuários. POST com resposta ambígua (erro de rede/5xx) não é repetido automaticamente.
- A senha nunca é exibida, registrada ou armazenada; o acesso inicial será por TAP (Sprint 7).
- O grupo de licença **não** é aplicado agora: fica para D-1 (Sprint 7).

## Ciclo de vida e acesso inicial (Sprint 7)

```text
Logic App (de hora em hora) ── token MI para api://<client-id> ──► POST /interno/ciclo-de-vida
                                                                   (App Role Provisionamento.Agendador)
   D-1: entra no grupo de licença (ou SKU direto)     conta_criada ─► licenciada
   D0 : accountEnabled=true                             licenciada  ─► ativa
Gestor ─► Minha equipe ─► "Gerar acesso inicial" ─► TAP de uso único (exibido uma vez)
```

- Motor nativo, sem Entra ID Governance. Detalhes em [CICLO_DE_VIDA.md](CICLO_DE_VIDA.md).
- O papel `Provisionamento.Agendador` só aceita aplicações (`allowedMemberTypes: Application`) e é atribuído apenas à Managed Identity; por isso o endpoint interno dispensa CSRF.
- A ativação só ocorre depois que a licença (quando o perfil tiver) foi atribuída.
