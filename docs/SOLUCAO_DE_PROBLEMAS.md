# Solução de problemas

As telas do portal usam linguagem simples. O detalhe técnico de cada falha (código do Microsoft Graph, permissão que faltou, script a executar) fica no **log** do App Service / Application Insights, nunca na tela.

Onde ver o log: portal do Azure → App Service do portal → **Log stream**, ou Application Insights → **Logs** (`traces | where message has "REQ-"`).

| Mensagem na tela | Causa provável | O que fazer |
|---|---|---|
| "O portal não tem permissão … no Microsoft 365 (código 403)" | A Managed Identity não tem a permissão do Graph para a etapa | Rode `scripts/Set-GraphPermissions.ps1` com o nível necessário (`criacao`, `ciclo-de-vida` ou `desligamento`) e reinicie o App Service. No desligamento, contas com funções administrativas também dão 403: remova a função antes. |
| "Não há licenças disponíveis no Microsoft 365" | Todas as unidades da licença do perfil estão em uso | Compre licenças ou libere unidades; o agendador tenta de novo sozinho. |
| "O Microsoft 365 recusou o código de acesso para este colaborador" | Política de Temporary Access Pass desativada ou sem incluir o usuário | Entra → Métodos de autenticação → Temporary Access Pass: habilite e inclua o grupo dos colaboradores. |
| "O acesso inicial por código temporário está desativado" | Mesma política, desabilitada | Idem acima. |
| "O Microsoft 365 não respondeu agora" / "pediu uma pausa" | Instabilidade ou limite de chamadas | Nada: o agendador tenta de novo na próxima hora. |
| "Não foi possível ler o Microsoft 365" (Administração → Recursos) | Falta o nível `leitura` | `Set-GraphPermissions.ps1 -Nivel leitura`, reinicie e aguarde alguns minutos. |
| "Limite diário de N contas criadas atingido" | Proteção `PROVISIONING_DAILY_LIMIT` | Aguarde o dia seguinte ou aumente o limite nas configurações do App Service. |
| "O domínio de e-mail do portal não está configurado" | `M365_DEFAULT_DOMAIN` vazio | Defina a variável com um domínio verificado e reinicie. |

Configurações citadas nas telas de administração (em "Como definir…"): `LGPD_RETENTION_DAYS`, `PRIVACY_CONTACT`, `LICENSE_MODE`, `TAP_LIFETIME_MINUTES`. Todas estão descritas em `.env.example` e em [IMPLANTACAO.md](IMPLANTACAO.md).
