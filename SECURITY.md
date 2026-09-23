# Política de Segurança

## Como relatar uma vulnerabilidade

**Não abra issue pública.** Use o recurso [Report a vulnerability](../../security/advisories/new) (GitHub Security Advisories) deste repositório.

Inclua: descrição, impacto, passos para reproduzir e versão afetada. Não inclua dados reais do seu tenant.

Respondemos em até 7 dias.

## Escopo

Como o portal escreve no Entra ID com permissões amplas do Microsoft Graph, são especialmente relevantes:

- contorno de autenticação/autorização (App Roles, tenant);
- escalonamento de privilégio (adicionar usuário a grupos fora da allowlist);
- vazamento de TAP, senhas ou tokens;
- injeção em campos do formulário que chegam ao Graph.

## Versões suportadas

Apenas a versão mais recente da branch `main` recebe correções.
