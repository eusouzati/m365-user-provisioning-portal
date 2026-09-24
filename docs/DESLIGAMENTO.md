# Desligamento de colaboradores

O RH pede o desligamento no portal, outra pessoa aprova e o agendador executa no horário do bloqueio. **A conta nunca é excluída**: fica bloqueada no Entra ID (retenção, auditoria e LGPD). A exclusão, se um dia for necessária, é feita manualmente por um administrador.

## Fluxo

| Quando | O que acontece | Status |
|---|---|---|
| RH envia | Colaborador escolhido na busca do diretório; último dia de trabalho; opção *bloquear imediatamente* | `enviada` |
| Aprovação | Outra pessoa aprova (quem pediu não aprova; ninguém aprova o próprio desligamento). O colaborador é conferido de novo no tenant | `aprovada` (*Desligamento agendado*) |
| Último dia, às `OFFBOARDING_BLOCK_HOUR` (padrão 18:00) | Etapas abaixo, executadas pelo agendador (de hora em hora) | `desligada` |

Com *bloquear imediatamente* (ou se o horário já passou), tudo acontece logo após a aprovação. Antes da execução, quem pediu (ou um Administrador) pode **cancelar o desligamento agendado**. O Administrador também pode **executar agora**.

## Etapas

1. **Bloquear a conta** (`accountEnabled=false`) — sempre a primeira.
2. **Revogar as sessões ativas** (`revokeSignInSessions`) — derruba Outlook, Teams e navegadores em até alguns minutos.
3. **Registrar a data de desligamento** (`employeeLeaveDateTime`).
4. **Remover dos grupos** em que é membro direto, inclusive o grupo de licença (a licença sai junto). A lista é conferida **no momento do bloqueio**, não no pedido.
5. Com `LICENSE_MODE=direct`, **remover as licenças atribuídas diretamente**.

### Ações manuais

O portal não faz — e registra como **Ação manual** na solicitação:

| Situação | Por quê |
|---|---|
| Grupo dinâmico | A associação vem de uma regra; ajuste a regra ou os atributos do usuário |
| Lista de distribuição / grupo de segurança habilitado para e-mail | Gerenciados pelo Exchange, não pelo Graph |
| Grupo com funções administrativas | Exige privilégio de administrador; o portal não recebe essa permissão |
| Grupo sincronizado do AD local | Só pode ser alterado no Active Directory |
| Licença atribuída diretamente com `LICENSE_MODE=group` | Remova no Centro de administração do Microsoft 365 |
| Subordinados diretos | O portal não altera o gestor de outras pessoas |
| Funções administrativas do Entra ID | O Graph não permite que o portal bloqueie administradores; remova as funções antes |

## Regras de segurança

- Ninguém pede, aprova, rejeita ou cancela o **próprio** desligamento; quem pediu não aprova. O colaborador em desligamento também não vê o pedido (nem na fila de aprovação), mesmo que seja Aprovador ou Administrador.
- Um colaborador só pode ter **um** desligamento em andamento.
- **Contratado que não compareceu:** se a conta ainda tem admissão em andamento, a revisão avisa e a aprovação do desligamento **encerra a admissão** — a conta nunca será ativada. O agendador também nunca ativa, licencia nem gera acesso inicial (TAP) para uma conta com desligamento aprovado.
- A busca inclui contas já desativadas, para concluir a remoção de acessos.
- Antes de escrever no Microsoft 365, a execução **reserva** a solicitação: a partir daí ela não pode mais ser cancelada, e execuções simultâneas (agendador × botão do Administrador) não se sobrepõem.
- O colaborador é escolhido pelo **Object ID** da busca e conferido no backend; o navegador não escolhe grupos.
- Falhas não desfazem o que já foi feito: a solicitação fica em `falha_parcial` e o agendador tenta de novo na próxima hora (ou o Administrador clica em *Reprocessar etapas pendentes*).
- `DRY_RUN=true`: tudo é apenas simulado.
- Observação é opcional e **não deve conter o motivo do desligamento** (minimização de dados — LGPD).

## Configuração

| Variável | Padrão | Descrição |
|---|---|---|
| `OFFBOARDING_BLOCK_HOUR` | `18` | Hora local (0–23) do último dia em que a conta é bloqueada |
| `TIMEZONE` | `America/Sao_Paulo` | Fuso usado para o horário do bloqueio |
| `LICENSE_MODE` | `group` | `direct` também remove licenças atribuídas diretamente |

Permissão adicional: `./scripts/Set-GraphPermissions.ps1 -Environment lab -Nivel desligamento` (`User.RevokeSessions.All`).

## Reverter um desligamento

Não há "desfazer" automático. A solicitação registra cada grupo removido; para readmitir, um administrador reativa a conta no Entra ID e recoloca os grupos (ou o RH faz uma nova admissão).
