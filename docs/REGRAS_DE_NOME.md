# Regras de geração de nome, UPN e e-mail

Implementadas em `app/core/naming.py` (funções puras, com testes em `tests/test_naming.py`).

## Padrão

`UPN_PATTERN` (padrão `{nome}.{ultimo_sobrenome}`). Campos disponíveis:

| Campo | "João Carlos" / "da Silva Pereira" |
|---|---|
| `{nome}` | `joao` |
| `{inicial_nome}` | `j` |
| `{primeiro_sobrenome}` | `silva` |
| `{ultimo_sobrenome}` | `pereira` |
| `{sobrenomes}` | `silva.pereira` |

Entre os campos só são permitidos `.`, `_` e `-`. O domínio é `M365_DEFAULT_DOMAIN`, que precisa estar verificado no tenant.

## Normalização

- Acentos removidos: `Conceição` → `conceicao`, `Weiß` → `weiss`, `Łukasz` → `lukasz`.
- Apóstrofos removidos: `D'Ávila` → `davila`. Hífen mantido: `Ana-Maria` → `ana-maria`.
- Partículas ignoradas no sobrenome (`UPN_PARTICLES`): `da`, `de`, `dos`, `e`, `van`...
  Se o sobrenome for só partícula (ex.: "Van"), ela é usada.
- Parte local limitada a 64 caracteres, sem separadores repetidos ou nas pontas.
- Nomes sem letras latinas utilizáveis (ex.: 李 王) são recusados com mensagem clara — defina outro padrão ou informe a grafia latina.

## Colisões

O endereço candidato é verificado contra **usuários e grupos**: `userPrincipalName`, `mail`, `mailNickname` e `proxyAddresses` (aliases). Se estiver em uso, tenta `joao.silva2`, `joao.silva3`… até 50 tentativas. A tela de revisão avisa quando o nome foi alterado.

O e-mail é igual ao UPN; o `mailNickname` é a parte local.

## Outras validações da solicitação

| Regra | Onde |
|---|---|
| Campos com os limites do Microsoft Graph (ex.: matrícula até 16, departamento até 64) | `app/core/requests.py` |
| Perfil existe, está ativo e é do mesmo tipo de colaborador | `app/services/onboarding.py` |
| Gestor existe no diretório e está ativo | idem |
| Matrícula (`employeeId`) não pertence a outro usuário | idem |
| Admissão entre hoje − `HIRE_DATE_PAST_DAYS` e hoje + `HIRE_DATE_FUTURE_DAYS` | idem |

No envio, tudo é recalculado no servidor; valores exibidos na revisão nunca são aceitos do navegador.
