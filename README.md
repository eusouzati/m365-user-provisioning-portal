# Portal de Provisionamento de Usuários Microsoft 365

Portal **open source** (licença MIT), em português, que automatiza a **entrada e a saída de colaboradores** no Microsoft 365 / Entra ID a partir dos pedidos do RH — com aprovação, conta criada desativada, licença na véspera da admissão, acesso inicial seguro (Temporary Access Pass), desligamento agendado e trilha de auditoria.

Cada organização implanta o portal **no próprio Microsoft 365 e na própria assinatura Azure**. Nenhum dado de cliente fica neste repositório e **o projeto não usa senhas nem segredos** (Managed Identity e OIDC).

> **Versão estável: 1.0.0** · [Notas da versão](docs/notas-de-versao/v1.0.0.md) · [CHANGELOG](CHANGELOG.md)
>
> **[Baixar a documentação completa em PDF](docs/Documentacao-Portal-Provisionamento-M365.pdf)** — 25 páginas para gestores e equipes técnicas, com telas. No GitHub, abra o arquivo e use o botão **Download**.

---

## Sumário

1. [O que o portal faz](#1-o-que-o-portal-faz)
2. [Como funciona (visão rápida)](#2-como-funciona-visão-rápida)
3. [Antes de começar: requisitos](#3-antes-de-começar-requisitos)
4. [Conceitos que você vai encontrar](#4-conceitos-que-você-vai-encontrar)
5. [Parte A — Preparar o seu computador](#parte-a--preparar-o-seu-computador)
6. [Parte B — Implantar no laboratório (passo a passo)](#parte-b--implantar-no-laboratório-passo-a-passo)
7. [Parte C — Primeiro uso e teste em modo simulação](#parte-c--primeiro-uso-e-teste-em-modo-simulação)
8. [Parte D — Ligar a execução real no Microsoft 365](#parte-d--ligar-a-execução-real-no-microsoft-365)
9. [Parte E — Publicação automática pelo GitHub (opcional)](#parte-e--publicação-automática-pelo-github-opcional)
10. [Parte F — Produção](#parte-f--produção)
11. [Uso no dia a dia](#uso-no-dia-a-dia)
12. [Atualizar para uma nova versão](#atualizar-para-uma-nova-versão)
13. [Problemas comuns](#problemas-comuns)
14. [Configurações (.env)](#configurações-env)
15. [Desenvolvimento local](#desenvolvimento-local)
16. [Estrutura do repositório](#estrutura-do-repositório)
17. [Documentação detalhada](#documentação-detalhada)
18. [Segurança, contribuição e licença](#segurança)

---

## 1. O que o portal faz

| Função | Resumo |
|---|---|
| **Admissão** | O RH preenche um formulário; o portal gera o login (`nome.sobrenome`), confere se ele já existe e mostra uma revisão antes de enviar. |
| **Aprovação** | Outra pessoa aprova (quem pede nunca aprova o próprio pedido). Os dados são conferidos de novo no Microsoft 365. |
| **Conta no momento certo** | A conta é criada **desativada** após a aprovação, recebe a licença **na véspera** e é **ativada no dia da admissão**. |
| **Primeiro acesso seguro** | O gestor gera um código de uso único (Temporary Access Pass), exibido uma só vez. O colaborador cria a própria senha e o MFA. Ninguém conhece a senha dele. |
| **Desligamento** | No último dia, no horário definido: conta bloqueada, sessões encerradas, saída dos grupos e licenças. A conta nunca é excluída automaticamente. |
| **Perfis de onboarding** | O administrador define os grupos e a licença de cada função; o RH só escolhe o perfil. |
| **Auditoria e LGPD** | Trilha de auditoria (quem fez o quê e quando), exportação para Excel, retenção configurável e anonimização de dados pessoais. |
| **Painel** | Pendências, falhas, admissões e desligamentos dos próximos dias, licenças disponíveis. |

## 2. Como funciona (visão rápida)

```text
RH solicita ──► Aprovador decide ──► Conta criada DESATIVADA (sem licença, com gestor e grupos)
                                              │
                            véspera da admissão: licença atribuída
                                              │
                              dia da admissão: conta ativada
                                              │
            gestor gera o código de acesso ──► colaborador cria senha e MFA
                                              │
          último dia de trabalho: conta bloqueada, sessões encerradas, grupos e licenças removidos
```

Por trás, um **agendador** (Logic App) chama o portal de hora em hora para executar as etapas agendadas. Tudo roda no **Azure App Service** da sua assinatura e fala com o Microsoft 365 pelo **Microsoft Graph**, usando uma **Managed Identity** (identidade sem senha). Detalhes: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## 3. Antes de começar: requisitos

### Contas e permissões necessárias

Confira **antes** de começar — é a causa mais comum de travar no meio.

| Onde | O que você precisa | Para quê |
|---|---|---|
| Microsoft 365 / Entra ID | **Administrador Global** (ou Administrador de Aplicativos **+** Administrador de Grupos **+** Administrador de Funções Privilegiadas) | Criar o registro de aplicativo do portal, os grupos de papéis e conceder permissões do Microsoft Graph |
| Azure | **Owner** (Proprietário) na assinatura | Criar os recursos e dar à identidade do portal acesso ao Storage |
| GitHub (opcional, Parte E) | Administrador do repositório (o seu fork) | Configurar a publicação automática |

### Organização (tenant)

| Item | Mínimo | Observação |
|---|---|---|
| Microsoft Entra ID | Free | **P1 recomendado** (licença por grupo e papéis atribuídos a grupos). Veja [docs/LICENCIAMENTO.md](docs/LICENCIAMENTO.md) |
| Contas | Somente nuvem | Se a empresa sincroniza usuários de um Active Directory local, o portal **não** serve (as contas precisam nascer no AD) |
| Assinatura Azure | Qualquer | Inclusive Free Trial para laboratório. Custos: [docs/CUSTOS.md](docs/CUSTOS.md) |

### Tempo estimado

- Laboratório funcionando em modo simulação: **1 a 2 horas** na primeira vez.
- Execução real + testes: **mais 1 hora**.

> **Dica:** faça tudo primeiro num ambiente de **laboratório** (`lab`). O portal começa em **modo simulação**: ele mostra o que faria, mas não altera nada no Microsoft 365 até você ligar a execução real (Parte D).

## 4. Conceitos que você vai encontrar

| Termo | O que é |
|---|---|
| **Tenant** | O "espaço" da sua organização no Microsoft 365. Tem um **Tenant ID** (um GUID). |
| **Assinatura Azure** | Onde os recursos do Azure são cobrados. Tem um **Subscription ID** (GUID). |
| **Microsoft Graph** | A interface oficial que o portal usa para ler e alterar usuários, grupos e licenças. |
| **Managed Identity** | Identidade do Azure para aplicações, **sem senha**. É ela que tem as permissões no Microsoft Graph. |
| **App Registration** | O cadastro do portal no Entra ID, usado para o login das pessoas. Não tem segredo. |
| **App Roles (papéis)** | Solicitante (RH), Aprovador, Administrador e Agendador (só o sistema). Dados por meio de grupos. |
| **UPN / login** | O nome de usuário no formato de e-mail, ex.: `maria.souza@empresa.com.br`. |
| **TAP** | Temporary Access Pass: código temporário de uso único para o primeiro acesso. |
| **DRY_RUN (modo simulação)** | `true` = não altera nada no Microsoft 365. `false` = execução real. |
| **`lab` / `production`** | Nome do ambiente. Cada um tem seus próprios recursos no Azure. |

Glossário completo no [PDF](docs/Documentacao-Portal-Provisionamento-M365.pdf) (Apêndice A).

---

## Parte A — Preparar o seu computador

Os comandos abaixo são para **Windows** com **PowerShell** (funciona também no PowerShell 7 em Linux/macOS; troque `.\` por `./` nos caminhos).

### A.1 Instalar as ferramentas

Abra o **PowerShell como usuário comum** e instale com o `winget` (vem no Windows 10/11):

```powershell
winget install --id Git.Git -e
winget install --id Microsoft.AzureCLI -e
winget install --id GitHub.cli -e
winget install --id Python.Python.3.12 -e
winget install --id Microsoft.PowerShell -e      # PowerShell 7 (recomendado)
```

**Feche e abra o PowerShell de novo** (para ele enxergar os programas novos). Depois:

```powershell
az bicep install
Install-Module Microsoft.Graph.Authentication -Scope CurrentUser    # responda "S"/"Y" se perguntar
```

### A.2 Permitir a execução dos scripts

O Windows bloqueia scripts `.ps1` por padrão. Libere só para o seu usuário:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### A.3 Conferir

```powershell
git --version
az version
az bicep version
gh --version
python --version        # 3.11 ou superior
```

Todos devem responder com um número de versão. Se algum disser "não é reconhecido", feche e abra o PowerShell ou reinstale aquele item.

---

## Parte B — Implantar no laboratório (passo a passo)

> Em cada passo há um **"Como saber se deu certo"**. Não siga para o próximo passo sem conferir.

### Passo 1 — Baixar o projeto

Recomendado: faça um **fork** deste repositório na sua conta do GitHub (botão *Fork*, no canto superior direito) e clone o **seu** fork — você vai precisar dele para a publicação automática (Parte E).

```powershell
mkdir C:\Projetos -Force
cd C:\Projetos
git clone https://github.com/<sua-conta>/m365-user-provisioning-portal.git
cd m365-user-provisioning-portal
```

### Passo 2 — Descobrir o Tenant ID, o Subscription ID e o domínio

```powershell
az login
az account list --output table
```

- **SubscriptionId**: a coluna `SubscriptionId` da assinatura que você vai usar.
- **TenantId**: a coluna `TenantId` da mesma linha.
- **Domínio**: no [Centro de administração do Microsoft 365](https://admin.microsoft.com) → *Configurações → Domínios*. Use um domínio **verificado**, ex.: `empresa.com.br` (ou `empresa.onmicrosoft.com` num laboratório).

### Passo 3 — Criar o arquivo de configuração `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Preencha **pelo menos**:

```text
AZURE_TENANT_ID=<o TenantId do passo 2>
AZURE_SUBSCRIPTION_ID=<o SubscriptionId do passo 2>
AZURE_LOCATION=brazilsouth
RESOURCE_PREFIX=m365up
M365_DEFAULT_DOMAIN=<seu domínio verificado>
```

Deixe o resto como está (inclusive `DRY_RUN=true`). Salve e feche.

- O `.env` **nunca** vai para o GitHub (está no `.gitignore`). Nenhum valor dele é segredo, mas ele identifica a sua organização.
- `RESOURCE_PREFIX` entra no nome dos recursos (ex.: `app-m365up-lab-xxxxx`). Use 3 a 8 letras minúsculas.
- Se a região `brazilsouth` não tiver o plano gratuito disponível na sua assinatura, rode `.\scripts\Find-AppServiceRegion.ps1` para descobrir uma que tenha.

### Passo 4 — Verificar os pré-requisitos (não altera nada)

```powershell
az login --tenant <TenantId>
az account set --subscription <SubscriptionId>
.\scripts\Test-Prerequisites.ps1 -TenantId <TenantId>
```

Uma janela do navegador vai pedir login para ler dados do Microsoft 365 (somente leitura).

**Como saber se deu certo:** o relatório final não mostra alertas vermelhos. Os avisos mais comuns e o que fazer:

| Aviso | O que fazer |
|---|---|
| Tenant sincronizado com AD local | O portal não se aplica a esse tenant |
| Sem Entra ID P1 | Funciona, mas use `LICENSE_MODE=direct` no `.env` e atribua os papéis a pessoas (não a grupos) |
| Temporary Access Pass desativado | Você vai habilitar na Parte D |

### Passo 5 — Criar a infraestrutura no Azure

Primeiro, **só a pré-visualização** (não cria nada):

```powershell
.\scripts\Deploy-Infrastructure.ps1 -Environment lab -WhatIfOnly
```

Confira a lista: grupo de recursos `rg-m365up-lab`, App Service (plano **F1, gratuito**), Managed Identity, Storage, Log Analytics e Application Insights. Então aplique:

```powershell
.\scripts\Deploy-Infrastructure.ps1 -Environment lab
```

Digite **`SIM`** (maiúsculas) quando pedir. Leva de 3 a 8 minutos.

**Como saber se deu certo:** a mensagem final de sucesso e um arquivo novo `infra-outputs.lab.json` na pasta do projeto (ele guarda os nomes dos recursos; também não vai para o GitHub).

> Erro `SubscriptionIsOverQuotaForSku`? Sua assinatura não tem cota do plano gratuito nessa região. Rode de novo com `-Location eastus2` (ou outra região do `Find-AppServiceRegion.ps1`). Veja [Problemas comuns](#problemas-comuns).

### Passo 6 — Publicar a aplicação

```powershell
.\scripts\Deploy-Application.ps1 -Environment lab
```

O primeiro deploy compila as dependências no Azure e pode levar **5 a 10 minutos** no plano gratuito.

**Como saber se deu certo:** o script termina com `OK https://app-m365up-lab-xxxxx.azurewebsites.net/health -> {"status":"healthy",...}`. Anote esse endereço: é o endereço do seu portal.

> Neste momento o portal ainda **não tem login** configurado — ele só responde ao `/health`. O login vem no próximo passo.

### Passo 7 — Configurar o login e os papéis (Entra ID)

```powershell
.\scripts\New-EntraApplication.ps1 -Environment lab -WhatIfOnly
.\scripts\New-EntraApplication.ps1 -Environment lab -AddMeToGroups Administradores,Solicitantes
```

Digite `SIM`. O navegador vai pedir login e **consentimento** para algumas permissões (usadas só durante o script). Use a conta de administrador.

O script cria, **sem nenhum segredo**:

- o App Registration `m365up-portal-lab` (login dos usuários);
- três grupos de segurança: `M365UP-Solicitantes-RH`, `M365UP-Aprovadores`, `M365UP-Administradores`;
- o papel `Agendador`, usado só pelo sistema;
- grava o `ENTRA_APP_CLIENT_ID` no seu `.env`.

> **Por que não me colocar em Aprovadores?** Quem pede não pode aprovar o próprio pedido. Para testar a aprovação, coloque **outra pessoa** (ou uma conta de teste) no grupo `M365UP-Aprovadores`, pelo [Entra admin center](https://entra.microsoft.com) → *Grupos*.

### Passo 8 — Ativar o login e o agendador

Rode a infraestrutura **de novo** (agora ela lê o `ENTRA_APP_CLIENT_ID` e liga o login e a Logic App):

```powershell
.\scripts\Deploy-Infrastructure.ps1 -Environment lab
```

Digite `SIM`.

**Como saber se deu certo:** abra o endereço do portal numa **janela anônima**. Ele deve pedir o login da Microsoft e, depois de entrar, mostrar "Olá, <seu nome>" com os papéis **Administrador** e **Solicitante (RH)**.

> Entrou mas aparece "ainda não possui papel"? Saia (`/.auth/logout`) e entre de novo — os papéis vêm no login. Se continuar, veja [Problemas comuns](#problemas-comuns).

### Passo 9 — Dar ao portal a permissão de leitura do Microsoft 365

```powershell
.\scripts\Set-GraphPermissions.ps1 -Environment lab -Nivel leitura
```

Digite `SIM`. Depois reinicie o portal para ele pegar a permissão nova:

```powershell
$out = Get-Content .\infra-outputs.lab.json | ConvertFrom-Json
az webapp restart -g $out.resourceGroupName -n $out.webAppName
```

**Como saber se deu certo:** no portal, **Administração → Recursos do Microsoft 365** mostra o nome da sua organização, os domínios, as licenças e os grupos. (Pode levar 5 a 10 minutos para a permissão valer; se aparecer "não foi possível ler o Microsoft 365", espere e clique em **Atualizar**.)

---

## Parte C — Primeiro uso e teste em modo simulação

O portal está em **modo simulação** (selo **Simulação** no topo): nada é alterado no Microsoft 365.

### C.1 Criar um perfil de onboarding

**Administração → Perfis de onboarding → Novo perfil**. Exemplo: *Financeiro — Funcionário*, com os grupos de acesso do setor e o grupo de licença.

> Ainda não tem um **grupo de licença**? No Entra admin center: *Grupos → Novo grupo* (tipo Segurança, ex.: `Licença - Microsoft 365 E3`) → abra o grupo → *Licenças* → *Atribuições* → escolha a licença. Exige Entra ID P1. Sem P1, use `LICENSE_MODE=direct` no `.env` e escolha a licença direto no perfil.

### C.2 Fazer uma admissão de teste

1. **Solicitações → Novo colaborador**: preencha com uma pessoa fictícia, escolha o perfil e um gestor (busque pelo nome).
2. **Revisar** → confira o login gerado → **Enviar solicitação**.
3. Entre com a **conta do aprovador** (outra pessoa) → **Aprovações** → abra o pedido → **Aprovar**.
4. Em simulação, as etapas aparecem como **Simulada**. Nada foi criado no Microsoft 365.

### C.3 Testar um desligamento

**Solicitações → Desligamento**: escolha um usuário de teste, informe o último dia e envie. A revisão mostra os grupos e licenças que seriam removidos.

---

## Parte D — Ligar a execução real no Microsoft 365

> Faça isso **só no laboratório** primeiro, com contas de teste.

### D.1 Conceder as permissões de escrita

O nível `desligamento` inclui todos os anteriores (leitura, criação, ciclo de vida):

```powershell
.\scripts\Set-GraphPermissions.ps1 -Environment lab -Nivel desligamento
```

Digite `SIM`. A lista de cada permissão e o motivo estão em [docs/PERMISSOES_GRAPH.md](docs/PERMISSOES_GRAPH.md).

### D.2 Habilitar o código de acesso temporário (TAP)

No [Entra admin center](https://entra.microsoft.com): *Proteção → Métodos de autenticação → Políticas → Temporary Access Pass* → **Habilitar**, destino *Todos os usuários* (ou um grupo que inclua os novos colaboradores) → em *Configurar*, marque **Uso único**.

### D.3 Desligar o modo simulação

No `.env`, troque:

```text
DRY_RUN=false
```

E aplique (o script avisa que o modo real será ativado):

```powershell
.\scripts\Deploy-Infrastructure.ps1 -Environment lab
$out = Get-Content .\infra-outputs.lab.json | ConvertFrom-Json
az webapp restart -g $out.resourceGroupName -n $out.webAppName
```

**Como saber se deu certo:** o selo **Simulação** some do topo do portal.

### D.4 Teste real de ponta a ponta

1. Faça uma admissão com **data de hoje** e aprove com outra conta.
2. Em **Administração → Todas as solicitações**, clique em **Executar ciclo de vida agora** (em vez de esperar a próxima hora).
3. No Entra admin center, confira o usuário: criado, com gestor, grupos e licença, e **ativado**.
4. Como **gestor** do colaborador, abra **Minha equipe → Gerar acesso inicial**. Anote o código.
5. Numa janela anônima, abra `https://mysignins.microsoft.com/security-info`, entre com o login novo e use o código como senha. Cadastre o MFA.
6. Faça o desligamento desse usuário com **bloquear imediatamente** e confira no Entra: conta bloqueada e fora dos grupos.

Para voltar ao modo seguro a qualquer momento: `DRY_RUN=true` no `.env` e rode `Deploy-Infrastructure.ps1` de novo.

### D.5 Opcional: LGPD

No `.env`:

```text
LGPD_RETENTION_DAYS=730
PRIVACY_CONTACT=dpo@suaempresa.com.br
```

Aplique com `Deploy-Infrastructure.ps1`. Detalhes em [docs/AUDITORIA_E_LGPD.md](docs/AUDITORIA_E_LGPD.md).

---

## Parte E — Publicação automática pelo GitHub (opcional)

Com isso, todo `git push` na branch `main` roda os testes e, se passarem, publica no laboratório — **sem nenhum segredo guardado no GitHub** (login federado OIDC).

```powershell
gh auth login                                              # entre com a sua conta do GitHub
.\scripts\New-GitHubDeployIdentity.ps1 -Environment lab -WhatIfOnly
.\scripts\New-GitHubDeployIdentity.ps1 -Environment lab    # digite SIM
```

**Como saber se deu certo:** faça uma alteração pequena (ex.: no README), `git commit` e `git push`, e acompanhe:

```powershell
gh run watch
```

O workflow **Deploy** deve terminar com todos os passos em verde, inclusive **Conferir /health**. Detalhes e erros comuns (como `AADSTS700213`): [docs/CI_CD.md](docs/CI_CD.md).

---

## Parte F — Produção

Repita as Partes B, D e E trocando `-Environment lab` por **`-Environment production`**, com estas diferenças:

- Use um plano pago que fica sempre ligado: `.\scripts\Deploy-Infrastructure.ps1 -Environment production -AppServiceSku B1`.
- Use grupos de papéis com as pessoas reais do RH, da TI e da administração.
- Em produção, a publicação pelo GitHub é **manual e com aprovação**: *Actions → Deploy → Run workflow → production*.

Antes de liberar para os usuários, siga o **[checklist de produção](docs/CHECKLIST_PRODUCAO.md)** (MFA por acesso condicional, proteção da `main`, revisão de permissões, teste de ponta a ponta).

---

## Uso no dia a dia

| Quem | Onde | O que faz |
|---|---|---|
| RH | **Solicitações** | Pede admissões e desligamentos; acompanha o andamento |
| Aprovador (TI) | **Aprovações** | Aprova ou rejeita (comentário obrigatório na rejeição) |
| Gestor | **Minha equipe** | No dia da admissão, gera o código de acesso e entrega pessoalmente |
| Administrador | **Administração** | Painel, perfis, recursos do Microsoft 365, auditoria, privacidade; reprocessa falhas |

**Dar ou tirar acesso ao portal:** inclua ou remova a pessoa do grupo `M365UP-Solicitantes-RH`, `M365UP-Aprovadores` ou `M365UP-Administradores` no Entra ID. Vale no próximo login da pessoa.

**Rotina recomendada para o administrador:** abrir o **Painel** todo dia (falhas e aprovações pendentes) e revisar os grupos de papéis e as permissões a cada trimestre.

## Atualizar para uma nova versão

```powershell
cd C:\Projetos\m365-user-provisioning-portal
git pull                                                  # se você usa um fork: sincronize antes (botão "Sync fork" no GitHub)
.\scripts\Deploy-Infrastructure.ps1 -Environment lab      # aplica mudanças de infraestrutura, se houver (pede SIM)
.\scripts\Deploy-Application.ps1 -Environment lab         # ou apenas git push, se usa a Parte E
```

Leia antes as [notas da versão](docs/notas-de-versao/) e o [CHANGELOG](CHANGELOG.md) — eles dizem se há permissão nova ou passo manual.

**Remover o portal:** os scripts nunca excluem nada. Para remover um ambiente, apague o grupo de recursos (`rg-m365up-lab`) no portal do Azure e, no Entra ID, o App Registration `m365up-portal-lab` e os três grupos. As contas criadas pelo portal **não** são afetadas.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `... não é reconhecido como nome de cmdlet` ao rodar um script | Política de execução do PowerShell | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `Instale o módulo: Install-Module Microsoft.Graph.Authentication` | Módulo ausente | `Install-Module Microsoft.Graph.Authentication -Scope CurrentUser` |
| `Sem sessão no Azure CLI` | Não fez login | `az login --tenant <TenantId>` |
| `SubscriptionIsOverQuotaForSku` | Assinatura sem cota do plano F1 na região | `-Location eastus2` (ou outra região do `Find-AppServiceRegion.ps1`), ou `-AppServiceSku B1` |
| Nome de Storage/Web App já em uso | Colisão de nomes globais | Troque o `RESOURCE_PREFIX` no `.env` |
| `/health` com 502 ou 503 logo após publicar | O plano gratuito ainda está compilando/reiniciando | Aguarde 2 a 5 minutos e abra de novo |
| `/health/ready` com 503 logo após criar a infraestrutura | Permissões do Storage propagando | Aguarde até 10 minutos |
| Entrei e "ainda não possui papel" | Não está em nenhum grupo de papéis, ou o login é antigo | Confira o grupo no Entra ID; saia e entre de novo |
| Sem Entra ID P1, os grupos de papéis não funcionam | Atribuição a grupos exige P1 | *Entra → Aplicativos empresariais → m365up-portal-lab → Usuários e grupos*: atribua o papel direto à pessoa |
| "O portal não tem permissão … (código 403)" | Falta o nível de permissão | `Set-GraphPermissions.ps1` com o nível necessário e reinicie o portal |
| "O Microsoft 365 recusou o código de acesso" | TAP desabilitado ou não inclui o usuário | Passo D.2 |
| O colaborador digita o login e aparece `login.live.com` | O navegador abriu conta pessoal | Janela anônima em `https://mysignins.microsoft.com/security-info` |
| Agendador não executa | Logic App sem permissão | Veja o histórico da Logic App no portal do Azure; se houver 401/403, rode `New-EntraApplication.ps1` de novo |
| `AADSTS700213` no GitHub Actions | Formato do subject OIDC | Rode `New-GitHubDeployIdentity.ps1` de novo ([docs/CI_CD.md](docs/CI_CD.md)) |

Mais casos, com as mensagens exatas das telas: [docs/SOLUCAO_DE_PROBLEMAS.md](docs/SOLUCAO_DE_PROBLEMAS.md). Logs ao vivo:

```powershell
$out = Get-Content .\infra-outputs.lab.json | ConvertFrom-Json
az webapp log tail -g $out.resourceGroupName -n $out.webAppName
```

## Configurações (.env)

As mais usadas (todas descritas em [.env.example](.env.example)). Depois de mudar, rode `Deploy-Infrastructure.ps1` para levar ao Azure.

| Configuração | Padrão | Para que serve |
|---|---|---|
| `DRY_RUN` | `true` | Modo simulação. `false` = altera o Microsoft 365 |
| `M365_DEFAULT_DOMAIN` | — | Domínio dos novos logins |
| `UPN_PATTERN` | `{nome}.{ultimo_sobrenome}` | Padrão do login ([docs/REGRAS_DE_NOME.md](docs/REGRAS_DE_NOME.md)) |
| `LICENSE_MODE` | `group` | `group` (recomendado, exige P1) ou `direct` |
| `LICENSE_LEAD_DAYS` | `1` | Dias antes da admissão para dar a licença |
| `TAP_LIFETIME_MINUTES` | `480` | Validade do código de acesso inicial |
| `OFFBOARDING_BLOCK_HOUR` | `18` | Hora do bloqueio no último dia |
| `PROVISIONING_DAILY_LIMIT` | `20` | Máximo de contas criadas por dia (proteção) |
| `TIMEZONE` | `America/Sao_Paulo` | Fuso de "hoje" e do horário de bloqueio |
| `LGPD_RETENTION_DAYS` | `0` | Dias para anonimizar (0 = desativado; sugestão 730) |
| `PRIVACY_CONTACT` | — | Contato do encarregado de dados (DPO) |

## Desenvolvimento local

Não precisa de Azure: o portal roda com dados simulados (organização fictícia "Contoso") e login simulado.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
uvicorn app.main:create_app --factory --reload   # http://localhost:8000
pytest                                            # testes
ruff check .                                      # lint
```

No `.env`, para desenvolvimento: `AUTH_MODE=dev`, `GRAPH_BACKEND=fake`, `STORAGE_BACKEND=sqlite` e `DEV_USER_ROLES` com os papéis que quiser simular. O `AUTH_MODE=dev` é recusado automaticamente no Azure.

## Estrutura do repositório

```text
app/            Aplicação FastAPI (rotas, regras, integração com o Graph, armazenamento, telas)
infra/          Infraestrutura como código (Bicep)
scripts/        PowerShell: pré-requisitos, infraestrutura, publicação, login, permissões, GitHub
docs/           Documentação (Markdown) e o PDF (fonte em docs/pdf/)
tests/          Testes automatizados
.github/        CI (testes, Bicep, segredos, CodeQL), publicação e Dependabot
```

## Documentação detalhada

| Tema | Documento |
|---|---|
| Documentação completa (gestores e técnicos) | [PDF](docs/Documentacao-Portal-Provisionamento-M365.pdf) |
| Implantação (referência) | [docs/IMPLANTACAO.md](docs/IMPLANTACAO.md) |
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

- Sem Client Secret: Microsoft Graph via **Managed Identity**, publicação via **GitHub OIDC**.
- O RH nunca vê credenciais; senhas e códigos de acesso nunca são registrados.
- CI com testes, cobertura, `pip-audit`, gitleaks e CodeQL. Detalhes em [docs/SEGURANCA.md](docs/SEGURANCA.md).
- Relate vulnerabilidades de forma privada, conforme [SECURITY.md](SECURITY.md).

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md) e o [Código de Conduta](CODE_OF_CONDUCT.md).

## Licença

[MIT](LICENSE)
