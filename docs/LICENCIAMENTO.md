# Licenciamento: o que funciona com cada plano do Entra ID

O portal é gratuito (licença MIT). O que muda de uma organização para outra é o plano do **Microsoft Entra ID** — incluído em várias assinaturas do Microsoft 365 (ex.: Microsoft 365 Business Premium e E3 incluem o P1; E5 inclui o P2).

| Recurso do portal | Free | P1 | P2 | Governance |
|---|:-:|:-:|:-:|:-:|
| Login com a conta corporativa e papéis do portal | ✔ | ✔ | ✔ | ✔ |
| Papéis atribuídos a **grupos** (Solicitantes, Aprovadores, Administradores) | — ¹ | ✔ | ✔ | ✔ |
| Admissão: conta desativada, gestor, grupos de acesso | ✔ | ✔ | ✔ | ✔ |
| Licença por **grupo** (`LICENSE_MODE=group`, recomendado) | — | ✔ | ✔ | ✔ |
| Licença **direta** na conta (`LICENSE_MODE=direct`) | ✔ | ✔ | ✔ | ✔ |
| Ativação no dia da admissão | ✔ | ✔ | ✔ | ✔ |
| Código de acesso inicial (Temporary Access Pass) | ✔ ² | ✔ | ✔ | ✔ |
| Desligamento (bloqueio, sessões, grupos, licenças) | ✔ | ✔ | ✔ | ✔ |
| Auditoria, painel e LGPD | ✔ | ✔ | ✔ | ✔ |
| Acesso condicional (exigir MFA para o portal) — recomendado | — | ✔ | ✔ | ✔ |
| Lifecycle Workflows nativos do Entra (`LIFECYCLE_ENGINE=entra_lcw`) | — | — | — | futuro ³ |

¹ Sem P1, atribua os papéis diretamente às pessoas em *Entra → Aplicativos empresariais → portal → Usuários e grupos*.
² A política de Temporary Access Pass está disponível em todos os planos; habilite-a em *Entra → Métodos de autenticação*.
³ O adaptador para Lifecycle Workflows ainda não está implementado; o motor do próprio portal funciona com qualquer plano.

A página **Administração → Recursos do Microsoft 365** mostra o que a sua organização tem e avisa quando a configuração do portal exige algo que falta (por exemplo, licença por grupo sem P1).

## Licenças dos colaboradores

O portal não compra licenças: ele atribui as que a organização já tem, conforme o perfil de onboarding, e só na véspera da admissão. No desligamento, a remoção dos grupos (inclusive o de licença) libera a licença. Quando faltam unidades, a etapa fica em *Falha parcial* e é tentada de novo a cada hora; o painel alerta quando restam 2 ou menos.
