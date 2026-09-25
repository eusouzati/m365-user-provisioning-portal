# Custos

O código do portal é gratuito (MIT). O custo é o dos serviços do Azure na **sua** assinatura. Valores de referência — confira sempre na [calculadora de preços do Azure](https://azure.microsoft.com/pricing/calculator/) para a sua região e moeda.

| Recurso | Laboratório | Produção (recomendado) | Observação |
|---|---|---|---|
| App Service (Linux) | **F1 — gratuito** | **B1** ou superior | F1 tem cota diária de CPU e não fica sempre ligado (o primeiro acesso do dia é lento). B1 permite *Always On* |
| Storage Account (Table, Standard LRS) | centavos/mês | centavos/mês | Volume pequeno: solicitações, perfis e auditoria |
| Log Analytics + Application Insights | normalmente dentro da franquia gratuita | conforme volume | Limite diário de 1 GB e amostragem de 50% configurados |
| Logic App (agendador, Consumo) | centavos/mês | centavos/mês | 1 execução por hora ≈ 720 execuções/mês |
| Managed Identity | gratuito | gratuito | |
| GitHub Actions | gratuito em repositório público | gratuito/franquia | Ambientes com aprovação exigem repositório público ou plano pago |

## Como economizar

- Use F1 no laboratório e B1 só em produção (`-AppServiceSku B1` no `Deploy-Infrastructure.ps1`).
- Mantenha o limite diário de logs (`logDailyCapGb`) — é a principal fonte de custo inesperado.
- Não crie ambientes que não usa; o script nunca exclui recursos, então remova manualmente o grupo de recursos de um laboratório que não quer mais.

## Economia no Microsoft 365

As licenças são atribuídas só na véspera da admissão e liberadas no desligamento, e pedidos rejeitados ou cancelados nunca consomem licença. Em organizações com rotatividade, isso tende a economizar mais do que o custo da infraestrutura.
