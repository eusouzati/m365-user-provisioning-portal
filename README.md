# Portal de Provisionamento de Usuários Microsoft 365

Portal **open source** (licença MIT) para automatizar a entrada e a saída de colaboradores no **Microsoft 365 / Entra ID** a partir das solicitações do RH — com aprovação, conta criada desativada, licença perto da admissão, acesso inicial via **Temporary Access Pass** e auditoria.

Cada organização implanta o portal **no próprio tenant e na própria assinatura Azure**. Nenhum dado de tenant fica neste repositório.

> **Status:** versão estável **1.0.0**. Admissão, aprovação, acesso inicial, desligamento, auditoria, LGPD e publicação automática pelo GitHub. Veja o [CHANGELOG](CHANGELOG.md).

## Documentação completa (PDF)

**[Baixar a documentação completa em PDF](docs/Documentacao-Portal-Provisionamento-M365.pdf)** — 25 páginas para gestores e equipes técnicas: por que implantar, benefícios e riscos evitados, todas as funcionalidades com telas, arquitetura, segurança, permissões, implantação passo a passo, operação e glossário.

No GitHub, abra o arquivo e use o botão **Download** (ícone de seta, no canto superior direito da visualização). A fonte do PDF está em [`docs/pdf/`](docs/pdf/) e pode ser regerada com `python docs/pdf/gerar_pdf.py`.

## Como funciona

```text
RH solicita → Aprovação → Conta criada DESATIVADA e sem licença
→ D-1: entra no grupo de licença → D0: conta ativada + gestor gera o TAP
→ Colaborador registra MFA no primeiro acesso → tudo auditado
```

Desligamento: RH pede → aprovação → no último dia a conta é bloqueada, as sessões são revogadas e o colaborador sai dos grupos e das licenças. A conta nunca é excluída automaticamente. Veja [docs/DESLIGAMENTO.md](docs/DESLIGAMENTO.md).

## Requisitos

| Item | Mínimo |
|---|---|
| Microsoft Entra ID | Free (núcleo) · P1 recomendado (licenciamento por grupo) · Governance opcional (Lifecycle Workflows) |
| Tenant | Somente nuvem (sem sincronização com AD local) |
| Azure | Qualquer assinatura (inclusive Free Trial para laboratório) |
| Ferramentas | Windows PowerShell 5.1 ou PowerShell 7+, Azure CLI + Bicep, Python 3.11+, Git, GitHub CLI |

## Início rápido (laboratório)

```powershell
git clone https://github.com/<voce>/m365-user-provisioning-portal.git
cd m365-user-provisioning-portal
Copy-Item .env.example .env      # preencha AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, M365_DEFAULT_DOMAIN

pwsh ./scripts/Test-Prerequisites.ps1 -TenantId <seu-tenant-id>   # somente leitura
az login --tenant <seu-tenant-id>
az bicep install

pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab -WhatIfOnly   # pré-visualização
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab               # cria (pede confirmação)
pwsh ./scripts/Deploy-Application.ps1 -Environment lab                  # publica e testa /health

pwsh ./scripts/New-EntraApplication.ps1 -Environment lab -AddMeToGroups Administradores   # login + papéis
pwsh ./scripts/Deploy-Infrastructure.ps1 -Environment lab               # ativa o login no App Service

pwsh ./scripts/Set-GraphPermissions.ps1 -Environment lab                # leitura do Graph pela Managed Identity
```

Permissões do Microsoft Graph: [docs/PERMISSOES_GRAPH.md](docs/PERMISSOES_GRAPH.md).

Guia completo: [docs/IMPLANTACAO.md](docs/IMPLANTACAO.md) · Login e papéis: [docs/CONFIGURACAO_ENTRA.md](docs/CONFIGURACAO_ENTRA.md).

## Desenvolvimento local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
uvicorn app.main:create_app --factory --reload   # http://localhost:8000 (AUTH_MODE=dev)
pytest
ruff check .
```

## Estrutura

```text
app/        FastAPI (portal + API)
infra/      Bicep
scripts/    PowerShell de apoio
docs/       Documentação
tests/      Testes
```

## Documentação

| Tema | Documento |
|---|---|
| Implantação do zero no seu tenant | [docs/IMPLANTACAO.md](docs/IMPLANTACAO.md) |
| Checklist para produção | [docs/CHECKLIST_PRODUCAO.md](docs/CHECKLIST_PRODUCAO.md) |
| Login, papéis e grupos | [docs/CONFIGURACAO_ENTRA.md](docs/CONFIGURACAO_ENTRA.md) |
| Permissões do Microsoft Graph | [docs/PERMISSOES_GRAPH.md](docs/PERMISSOES_GRAPH.md) |
| O que funciona com Free / P1 / P2 / Governance | [docs/LICENCIAMENTO.md](docs/LICENCIAMENTO.md) |
| Custos | [docs/CUSTOS.md](docs/CUSTOS.md) |
| Arquitetura | [docs/ARQUITETURA.md](docs/ARQUITETURA.md) |
| Ciclo de vida (véspera, dia da admissão, acesso inicial) | [docs/CICLO_DE_VIDA.md](docs/CICLO_DE_VIDA.md) |
| Desligamento | [docs/DESLIGAMENTO.md](docs/DESLIGAMENTO.md) |
| Auditoria, painel e LGPD | [docs/AUDITORIA_E_LGPD.md](docs/AUDITORIA_E_LGPD.md) |
| Regras de nome e login | [docs/REGRAS_DE_NOME.md](docs/REGRAS_DE_NOME.md) |
| Publicação automática (GitHub Actions + OIDC) | [docs/CI_CD.md](docs/CI_CD.md) |
| Segurança e revisão da v1.0 | [docs/SEGURANCA.md](docs/SEGURANCA.md) |
| Solução de problemas | [docs/SOLUCAO_DE_PROBLEMAS.md](docs/SOLUCAO_DE_PROBLEMAS.md) |

## Segurança

- Sem Client Secret: Microsoft Graph via **Managed Identity**, deploy via **GitHub OIDC**.
- CI com testes, cobertura, `pip-audit`, gitleaks e CodeQL. Detalhes em [docs/SEGURANCA.md](docs/SEGURANCA.md).
- O RH nunca vê credenciais; senhas e TAP nunca são registrados.
- Relate vulnerabilidades conforme [SECURITY.md](SECURITY.md).

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md) e o [Código de Conduta](CODE_OF_CONDUCT.md).

## Licença

[MIT](LICENSE)
