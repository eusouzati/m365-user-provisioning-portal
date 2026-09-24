# Ciclo de vida do colaborador

## Linha do tempo (entrada)

| Quando | O que acontece | Status |
|---|---|---|
| Aprovação | Conta criada **desativada**, sem licença, com gestor e grupos de acesso | `conta_criada` |
| D-1 (`LICENSE_LEAD_DAYS`) | Licença: entra no grupo de licença do perfil (`LICENSE_MODE=group`) ou recebe o SKU direto (`direct`) | `licenciada` |
| D0 (admissão) | Conta **ativada** (`accountEnabled=true`) | `ativa` |
| D0 | O **gestor** gera o acesso inicial (TAP) em *Minha equipe* | `ativa` |

Admissões com data passada (ou licença atrasada) são resolvidas na próxima execução, na ordem certa: licença primeiro, ativação depois.

## Motor nativo

`app/services/lifecycle.py`, executado:

- **de hora em hora** pela Logic App `logic-<prefixo>-<ambiente>`, que chama `POST /interno/ciclo-de-vida` com a Managed Identity;
- **sob demanda** pelo Administrador (*Todas as solicitações → Executar ciclo de vida agora*).

Propriedades:

- **Idempotente** — rodar várias vezes não duplica nada.
- **Novas tentativas** — uma etapa que falhou (ex.: sem licenças disponíveis) é tentada de novo na próxima hora; a solicitação fica em `falha_parcial` até resolver.
- **Revalidação** — o grupo de licença é conferido no tenant antes do uso; com SKU direto, verifica unidades disponíveis.
- **DRY_RUN** — com `DRY_RUN=true` o motor não altera nada.
- Fuso horário: `TIMEZONE` (padrão `America/Sao_Paulo`) define o "hoje".

## Acesso inicial (Temporary Access Pass)

- Somente o **gestor registrado na solicitação** pode gerar, e somente para contas `ativa`.
- TAP de **uso único**, validade = menor valor entre `TAP_LIFETIME_MINUTES` e o máximo da política do tenant.
- Gerar de novo substitui o anterior (o Entra permite um TAP por usuário).
- O código é exibido **uma única vez**, com `Cache-Control: no-store`; nunca é gravado, registrado em log ou enviado por e-mail. O histórico registra apenas quem gerou e quando.
- O colaborador usa o TAP em `https://mysignins.microsoft.com/security-info` para cadastrar MFA / Windows Hello. Se o navegador abrir `login.live.com` (conta pessoal), o login corporativo não será encontrado: use janela anônima ou `https://login.microsoftonline.com`.

## Lifecycle Workflows (Entra ID Governance)

Tenants com Entra ID Governance podem, no futuro, usar os *Lifecycle Workflows* nativos (`LIFECYCLE_ENGINE=entra_lcw`). Este adaptador ainda não está implementado; o motor nativo funciona com Entra ID P1.
