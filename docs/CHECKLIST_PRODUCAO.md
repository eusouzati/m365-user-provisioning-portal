# Checklist para entrar em produção

Use depois de validar tudo no ambiente de laboratório.

## Microsoft 365 / Entra ID

- [ ] Tenant somente nuvem (sem sincronização com AD local).
- [ ] Política de **Temporary Access Pass** habilitada e incluindo os novos colaboradores (uso único).
- [ ] Grupo(s) de licença criados, com a licença atribuída (se `LICENSE_MODE=group`, exige P1).
- [ ] Grupos de papéis do portal com os membros certos; ninguém é Solicitante **e** Aprovador sem necessidade.
- [ ] **Acesso condicional** exigindo MFA para o aplicativo `<prefixo>-portal-production`.
- [ ] Permissões da Managed Identity revisadas (*Aplicativos empresariais → Identidades gerenciadas*): só os níveis que você usa.

## Azure

- [ ] Ambiente `production` separado do `lab` (outro grupo de recursos, outra identidade).
- [ ] App Service **B1 ou superior** (Always On).
- [ ] `DRY_RUN=false` só depois de testar admissão, desligamento e acesso inicial em laboratório.
- [ ] `PROVISIONING_DAILY_LIMIT` adequado ao volume da empresa.
- [ ] `TIMEZONE` e `OFFBOARDING_BLOCK_HOUR` conferidos.
- [ ] `LGPD_RETENTION_DAYS` e `PRIVACY_CONTACT` definidos com o encarregado de dados (DPO).
- [ ] Alerta no Application Insights para falhas (opcional, recomendado): execução do agendador com falha e respostas 5xx.

## GitHub

- [ ] `main` protegida: pull request obrigatório, CI (`testes`, `bicep`, `segredos`, `CodeQL`) obrigatório, sem push direto.
- [ ] Poucas pessoas com permissão de escrita no repositório.
- [ ] Ambiente `production` com **aprovação obrigatória** (`New-GitHubDeployIdentity.ps1 -Environment production`).
- [ ] Dependabot ativo; PRs revisados antes do merge.

## Operação

- [ ] Responsável definido para olhar o **Painel** diariamente (falhas e aprovações pendentes).
- [ ] RH, aprovadores e gestores orientados (a [documentação em PDF](Documentacao-Portal-Provisionamento-M365.pdf) serve de material).
- [ ] Teste de ponta a ponta em produção com um colaborador de teste: admissão → aprovação → véspera → dia da admissão → código de acesso → desligamento.
- [ ] Revisão trimestral: membros dos grupos de papéis, permissões da identidade e exportação da auditoria (se a política da empresa pedir).
