# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Sprint 4: formulário de novo colaborador (campos com limites do Graph, busca de gestor), motor de nomes/UPN configurável (acentos, partículas, colisões `joao.silva` → `joao.silva2` verificadas em UPN, e-mail, alias e proxyAddresses de usuários e grupos), checagem de matrícula duplicada, tela "Revisar criação do usuário" com linha do tempo D-1/D0 e envio **simulado** (nada é gravado nem criado).
- Sprint 3: `GraphService` somente leitura (Managed Identity, paginação, retry com `Retry-After`, bloqueio de escrita); página de capacidades do tenant (licenças, P1/P2/Governance, TAP, domínios, grupos); perfis de onboarding (grupos de acesso + licença) validados contra o tenant no backend; APIs de busca de gestores e verificação de endereço; proteção CSRF; script `Set-GraphPermissions.ps1`; modo `GRAPH_BACKEND=fake`.
- Sprint 2: login com Microsoft Entra ID via App Service Authentication sem Client Secret (fluxo de ID token por padrão; Managed Identity como credencial federada opcional); App Roles Solicitante/Aprovador/Administrador atribuídos a grupos; validação de tenant, audiência e papéis no backend; modo `AUTH_MODE=dev` para desenvolvimento local; script `New-EntraApplication.ps1`.
- Sprint 1: estrutura do projeto, FastAPI com `/health` e `/health/ready`, cabeçalhos de segurança, armazenamento SQLite/Azure Table, infraestrutura Bicep (App Service, Managed Identity, Storage, Application Insights) e scripts de implantação.
