# Como contribuir

Obrigado pelo interesse! Este projeto é desenvolvido em português e em Sprints (veja `docs/ARQUITETURA.md`).

1. Abra uma issue descrevendo o problema ou a ideia antes de PRs grandes.
2. Faça um fork, crie um branch (`feat/minha-melhoria`) e rode `pre-commit install`.
3. Garanta `pytest` e `ruff check .` passando.
4. Abra o PR usando o modelo.

## Regras inegociáveis

- **Nunca** incluir Tenant ID, domínio, Group ID, SKU, nomes ou e-mails reais — use `contoso.com` e `00000000-0000-0000-0000-000000000000`.
- **Nunca** registrar senhas, TAP, tokens ou segredos em logs.
- Toda nova permissão do Microsoft Graph deve ser justificada em `docs/PERMISSOES_GRAPH.md`.
- O frontend nunca envia Group IDs/SKUs livres ao backend.
- Regras de negócio ficam em `app/core/` e devem ter testes.

## Commits

Mensagens em português no padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/): `feat:`, `fix:`, `docs:`, `ci:`, `refactor:`, `test:`.
