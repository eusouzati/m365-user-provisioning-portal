# Auditoria, painel e LGPD

## Trilha de auditoria

Toda gravação de solicitação ou perfil gera eventos automaticamente, deduzidos da diferença entre a versão anterior e a nova: nenhuma tela precisa "lembrar" de auditar.

| Evento | Quando |
|---|---|
| Solicitação enviada / aprovada / rejeitada / cancelada | Ações do RH e dos aprovadores |
| Conta criada · Licença atribuída · Conta ativada · Desligamento concluído · Falha parcial | Transições automáticas |
| Etapa concluída / com falha / ação manual | Cada etapa do provisionamento ou do desligamento (com quem disparou) |
| Acesso inicial (TAP) gerado | Gestor gerou o código — **o código nunca é registrado** |
| Perfil criado / alterado / excluído | Administração de perfis |
| Agendador executado | Execuções em que algo aconteceu (resumo) |
| Dados pessoais anonimizados | Retenção LGPD |
| Auditoria exportada | Alguém baixou o CSV |

Propriedades:

- **Somente acréscimo.** O portal não altera nem apaga eventos. No Azure ficam na tabela `auditoria` (partição por mês).
- **Minimização.** O alvo é o número da solicitação (`REQ-…`) ou do perfil. Nome, login, e-mail e matrícula do colaborador **não** entram na auditoria; comentários de pessoas (ex.: motivo de rejeição) ficam só na solicitação. Quem executou cada ação (ator) é mantido para responsabilização.
- **Nunca** contém senha, TAP, token ou segredo.
- Uma falha ao gravar a auditoria é registrada no log e não desfaz a operação.

Tela: **Administração → Auditoria** (filtros por ação, solicitação, pessoa e período; exportação CSV com separador `;`, pronta para o Excel e protegida contra injeção de fórmulas).

## Painel

**Administração → Painel**: aguardando aprovação, em andamento, com falha, admissões e desligamentos dos próximos 7 dias, última execução do agendador, licenças disponíveis (alerta com 2 ou menos), solicitações por status e atividade recente.

## LGPD

| Variável | Padrão | Descrição |
|---|---|---|
| `LGPD_RETENTION_DAYS` | `0` (desativado) | Dias após a conclusão para anonimizar os dados pessoais das solicitações. Sugestão: `730` |
| `PRIVACY_CONTACT` | vazio | Contato do encarregado de dados (DPO), exibido no aviso de privacidade |

Com o prazo definido, o agendador anonimiza automaticamente (também em `DRY_RUN`, pois são dados do portal). O Administrador vê o que está pronto e pode antecipar em **Administração → Privacidade (LGPD)**.

A anonimização remove nome, login, e-mail, matrícula, cargo, gestor, comentários e detalhes das etapas. Permanecem: número, tipo, status, datas, Object ID da conta no Entra (pseudônimo, para rastrear o que foi feito) e quem pediu e aprovou. **A conta no Microsoft 365 não é alterada.** Não pode ser desfeita.

Outras medidas:

- Aviso de privacidade em `/privacidade` (link no rodapé) — finalidade, dados, base legal, retenção e contato.
- O formulário de desligamento não pede o motivo e orienta a não informá-lo.
- Logs das bibliotecas do Azure e do cliente HTTP ficam em `WARNING` (as URLs do Graph podem conter identificadores); métricas ao vivo do Application Insights desativadas.

> Este portal ajuda a cumprir a LGPD, mas a política de retenção, a base legal e o registro das operações de tratamento são decisões da organização — valide com o seu encarregado de dados.
