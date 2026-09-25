# Segurança

Resumo do modelo de segurança do portal e do resultado da revisão da v1.0. Para relatar uma vulnerabilidade, veja [SECURITY.md](../SECURITY.md).

## O que o portal protege

O portal tem permissões de **aplicação** no Microsoft Graph que valem para toda a organização (criar contas, incluir em grupos, ativar/bloquear, gerar código de acesso temporário, encerrar sessões). O maior risco é alguém usar o portal para ganhar acesso indevido: criar uma conta falsa, entrar em grupos que não deveria ou obter o código de acesso de outra pessoa.

## Camadas de proteção

| Camada | Controle |
|---|---|
| Identidade do portal | Managed Identity atribuída pelo usuário — sem senha, certificado ou client secret |
| Login das pessoas | App Service Authentication (Entra ID, somente a organização). O backend só confia no cabeçalho de identidade se a autenticação do App Service estiver ativa e revalida organização (`tid`) e aplicativo (`aud`) |
| Autorização | App Roles verificados em **cada rota** do servidor (Solicitante, Aprovador, Administrador, Agendador). O papel Agendador só pode ser atribuído a aplicações |
| Segregação de funções | Quem pede não aprova; ninguém pede, aprova ou cancela o próprio desligamento; o colaborador em desligamento não vê o pedido. O aprovador é avisado quando quem pediu também é o gestor informado (e, portanto, quem gerará o código de acesso) |
| Grupos | O navegador nunca escolhe grupos: vêm do perfil de onboarding, revalidado no Microsoft 365 a cada uso. Grupos com funções administrativas, dinâmicos e os grupos de papéis do portal são bloqueados |
| Escrita no Microsoft 365 | Só existe com `DRY_RUN=false`; limite diário de contas; POST com resposta ambígua não é repetido; o portal não tem permissão para excluir usuários nem alterar administradores |
| Entrada de dados | Validação de tamanho e caracteres em todos os campos; literais OData escapados; IDs vindos do navegador validados por padrão (GUID/UPN) antes de irem para URLs do Graph |
| Formulários | CSRF: cookie `HttpOnly` + `SameSite=Strict` + token comparado em tempo constante + verificação de `Origin` |
| Navegador | CSP `default-src 'self'` sem script ou estilo inline, HSTS, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control: no-store` |
| Segredos | Senha inicial aleatória e descartada; código de acesso exibido uma vez e nunca gravado, registrado ou enviado |
| Dados e logs | Auditoria somente de acréscimo e sem dados pessoais do colaborador; logs das bibliotecas em `WARNING`; anonimização LGPD |
| Infraestrutura | HTTPS obrigatório, TLS 1.2+ (site, SCM e Storage), FTP e autenticação básica desativados, depuração remota desativada, Storage sem chaves de acesso (só RBAC), sem acesso público a blobs |
| Publicação | GitHub Actions com OIDC (sem segredo), escopo Website Contributor só no Web App, ambientes restritos à `main`, produção com aprovação |
| Código | CI com lint, 330+ testes, cobertura mínima de 85%, `pip-audit`, varredura de segredos (gitleaks) e CodeQL; Dependabot semanal |

## Revisão da v1.0 (Sprint 12)

Escopo: autenticação e autorização por rota, fluxos de aprovação e desligamento, CSRF, injeção em consultas do Graph e do Storage, criação/reuso de contas, geração do código de acesso, dados pessoais em logs e auditoria, infraestrutura (Bicep), scripts PowerShell, workflows do GitHub e histórico do Git.

| Achado | Gravidade | Situação |
|---|---|---|
| Quem pede uma admissão pode se indicar como gestor e, assim, gerar o código de acesso da conta nova | Média (exige outra pessoa aprovando) | **Mitigado:** aviso destacado para o aprovador; ação registrada na auditoria |
| TLS mínimo do site de implantação (SCM) e depuração remota não estavam explícitos no Bicep | Baixa | **Corrigido** (`scmMinTlsVersion: 1.2`, `remoteDebuggingEnabled: false`) |
| Storage permitia replicação entre organizações (padrão do Azure) | Baixa | **Corrigido** (`allowCrossTenantReplication: false`) |
| CI sem CodeQL e sem cobertura | Baixa | **Corrigido** (workflow CodeQL e `--cov-fail-under=85`) |
| Dependências desatualizadas (httpx, pydantic-settings, pytest, pip-audit, pre-commit, setup-python) | Informativa | **Atualizadas**; `pip-audit` sem vulnerabilidades conhecidas |
| O `/health` informa a versão sem login | Informativa | Aceito: necessário para a conferência do deploy; não expõe dados |
| Um desligamento aprovado pode bloquear qualquer conta comum da organização | Informativa | Por projeto: exige pedido + aprovação de outra pessoa; administradores do Entra não são afetados (o Graph recusa) |
| Nenhum identificador real de organização ou segredo nos arquivos versionados nem no histórico | — | Verificado |

## Riscos residuais e recomendações

- **Quem publica código ganha as permissões do portal.** Proteja a `main` (pull request + CI obrigatórios), limite quem tem escrita no repositório e mantenha produção com aprovação.
- **Permissões de aplicação valem para toda a organização.** Revise a cada trimestre em *Entra → Aplicativos empresariais → Identidades gerenciadas*.
- **Grupos de papéis do portal** (`<PREFIXO>-Solicitantes-RH`, `-Aprovadores`, `-Administradores`) são tão sensíveis quanto o próprio portal: mantenha poucos membros e revise periodicamente.
- **Acesso condicional:** exija MFA para o aplicativo do portal no Entra ID.
- Checklist completo antes de produção: [CHECKLIST_PRODUCAO.md](CHECKLIST_PRODUCAO.md).
