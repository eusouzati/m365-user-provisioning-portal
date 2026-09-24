<#
.SYNOPSIS
  Cria a identidade de deploy do GitHub Actions (OIDC, sem segredo) e configura o
  ambiente no GitHub.

.DESCRIPTION
  Idempotente e nunca exclui nada. Mostra o plano e só aplica após você digitar SIM.

  No Microsoft Entra ID / Azure:
    - App Registration "<prefixo>-github-deploy-<ambiente>" (somente este tenant),
      SEM segredo e SEM certificado
    - Credencial federada: aceita tokens do ambiente "<ambiente>" deste repositório
      (subject repo:<dono>/<repo>:environment:<ambiente>)
    - Papel "Website Contributor" SOMENTE no Web App do ambiente (nada na assinatura,
      no Storage ou no Entra ID). Atenção: publicar código no Web App equivale aos
      privilégios da própria aplicação (a Managed Identity dela) — por isso o ambiente
      no GitHub só aceita a branch main.

  No GitHub (via GitHub CLI):
    - Ambiente "<ambiente>" restrito à branch main (production: também exige sua aprovação)
    - Variáveis do ambiente (IDs, não são segredos): AZURE_CLIENT_ID, AZURE_TENANT_ID,
      AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_WEBAPP_NAME
    - Variável do repositório DEPLOY_<AMBIENTE>_ENABLED=true (liga o workflow Deploy)

  Requisitos: az login (Administrador Global ou Administrador de Aplicativos + Owner/
  User Access Administrator no Resource Group) e gh auth login (admin do repositório).

.EXAMPLE
  ./scripts/New-GitHubDeployIdentity.ps1 -Environment lab -WhatIfOnly
  ./scripts/New-GitHubDeployIdentity.ps1 -Environment lab
  ./scripts/New-GitHubDeployIdentity.ps1 -Environment production -Repository minhaorg/m365-user-provisioning-portal
#>
[CmdletBinding()]
param(
    [ValidateSet('lab', 'production')] [string] $Environment = 'lab',
    [string] $EnvFile = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env'),
    # dono/repositório no GitHub; padrão: o remoto "origin" desta pasta
    [string] $Repository = '',
    # Permite habilitar produção mesmo se o GitHub não aceitar a aprovação obrigatória
    [switch] $AllowUnprotectedProduction,
    [switch] $WhatIfOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Common.ps1"
Set-StrictMode -Off

# No Windows PowerShell 5.1, saída de erro de comandos nativos com ErrorAction=Stop
# vira exceção. Para chamadas que podem falhar de propósito, relaxa só durante a chamada.
function Invoke-Soft([scriptblock] $Block) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block 2>$null } finally { $ErrorActionPreference = $old }
}

$cfg = Import-DotEnv $EnvFile
$tenantId = Get-Required $cfg 'AZURE_TENANT_ID'
$subscriptionId = Get-Required $cfg 'AZURE_SUBSCRIPTION_ID'
$prefix = Get-Required $cfg 'RESOURCE_PREFIX'
Assert-AzureContext -TenantId $tenantId -SubscriptionId $subscriptionId
Assert-Command gh 'Instale o GitHub CLI: https://cli.github.com e rode gh auth login'

$outputsPath = Get-OutputsPath $Environment
if (-not (Test-Path $outputsPath)) { throw "Saídas da infraestrutura não encontradas ($outputsPath). Rode Deploy-Infrastructure.ps1 antes." }
$infra = Get-Content $outputsPath -Raw | ConvertFrom-Json
$rg = $infra.resourceGroupName
$webApp = $infra.webAppName

if (-not $Repository) {
    Push-Location (Split-Path $PSScriptRoot -Parent)
    try { $Repository = Invoke-Soft { gh repo view --json nameWithOwner --jq .nameWithOwner } } finally { Pop-Location }
    if (-not $Repository) { throw 'Não foi possível descobrir o repositório. Informe -Repository dono/repositorio.' }
}
$Repository = $Repository.Trim()
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw "Repositório inválido: $Repository" }
$repoInfo = Invoke-Soft { gh api "repos/$Repository" } | ConvertFrom-Json
if (-not $repoInfo -or -not $repoInfo.full_name) { throw "Repositório $Repository não encontrado ou sem acesso (gh auth login)." }
if (-not $repoInfo.permissions.admin) { throw "Você precisa ser administrador do repositório $Repository." }
$Repository = $repoInfo.full_name  # grafia exata (o subject do OIDC diferencia maiúsculas)

$appName = "$prefix-github-deploy-$Environment"
$subject = "repo:${Repository}:environment:$Environment"
$webAppId = az webapp show -g $rg -n $webApp --query id -o tsv
if (-not $webAppId) { throw "Web App $webApp não encontrado em $rg." }

# Filtro exato (--display-name faz "começa com")
$apps = @(az ad app list --filter "displayName eq '$appName'" -o json | ConvertFrom-Json)
if ($apps.Count -gt 1) { throw "Há $($apps.Count) App Registrations chamados '$appName'. Mantenha só um e rode de novo." }
$app = if ($apps.Count -eq 1) { $apps[0] } else { $null }
$sp = $null
$fics = @()
if ($app) {
    $sp = az ad sp list --filter "appId eq '$($app.appId)'" --query '[0]' -o json | ConvertFrom-Json
    $fics = @(az ad app federated-credential list --id $app.appId -o json | ConvertFrom-Json)
}
$ficName = "github-$Environment"
$ficOk = @($fics | Where-Object { $_.subject -ceq $subject -and $_.issuer -eq 'https://token.actions.githubusercontent.com' }).Count -gt 0
$ficExisting = @($fics | Where-Object { $_.name -eq $ficName }).Count -gt 0

function Mark([bool] $exists) { if ($exists) { '=' } else { '+' } }
Write-Host "`n== Plano — identidade de deploy do GitHub ($Environment) ==" -ForegroundColor Cyan
Write-Host "  $(Mark ($null -ne $app)) App Registration '$appName' (sem segredo, somente este tenant)"
Write-Host "  $(Mark ($null -ne $sp)) Service principal"
Write-Host "  $(Mark $ficOk) Credencial federada: $subject"
Write-Host "  ~ Papel 'Website Contributor' somente em $webApp (garantir)"
Write-Host "  ~ GitHub $Repository → ambiente '$Environment' (somente a branch main$(if ($Environment -eq 'production') { ' + aprovação obrigatória' }))"
Write-Host "  ~ Variáveis do ambiente: AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_WEBAPP_NAME"
Write-Host "  ~ Variável do repositório: DEPLOY_$($Environment.ToUpper())_ENABLED=true"
if ($app -and $app.passwordCredentials -and $app.passwordCredentials.Count -gt 0) {
    Write-Host "  ! O App Registration tem segredo(s) cadastrado(s); o deploy não usa segredos. Remova-os no portal do Entra." -ForegroundColor Yellow
}
Write-Host "`nNada será excluído. Nenhum segredo será criado." 
if ($WhatIfOnly) { Write-Host 'Somente pré-visualização (-WhatIfOnly).'; return }
if ((Read-Host "`nDigite SIM para aplicar") -cne 'SIM') { Write-Host 'Cancelado. Nada foi alterado.' -ForegroundColor Yellow; return }

# ---------------------------------------------------------------- Entra ID
if (-not $app) {
    Write-Host 'Criando App Registration...'
    $app = az ad app create --display-name $appName --sign-in-audience AzureADMyOrg -o json | ConvertFrom-Json
    if (-not $app) { throw 'Falha ao criar o App Registration.' }
}
if (-not $sp) {
    Write-Host 'Criando service principal...'
    $sp = az ad sp create --id $app.appId -o json | ConvertFrom-Json
    if (-not $sp) { throw 'Falha ao criar o service principal.' }
}
if (-not $ficOk) {
    Write-Host 'Criando credencial federada...'
    $tmp = Join-Path ([IO.Path]::GetTempPath()) "fic-$([guid]::NewGuid()).json"
    @{
        name        = $ficName
        issuer      = 'https://token.actions.githubusercontent.com'
        subject     = $subject
        audiences   = @('api://AzureADTokenExchange')
        description = "GitHub Actions ($Repository, ambiente $Environment)"
    } | ConvertTo-Json | Set-Content -Path $tmp -Encoding ASCII
    try {
        if ($ficExisting) {
            # mesmo nome, outro subject (ex.: repositório renomeado/transferido): atualiza
            az ad app federated-credential update --id $app.appId --federated-credential-id $ficName --parameters "@$tmp" -o none
        } else {
            az ad app federated-credential create --id $app.appId --parameters "@$tmp" -o none
        }
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao gravar a credencial federada.' }
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

Write-Host 'Garantindo o papel Website Contributor no Web App...'
# Consulta pelo escopo (sem depender da resolução do principal no Graph, que atrasa)
$existing = Invoke-Soft { az role assignment list --scope $webAppId --query "[?principalId=='$($sp.id)' && roleDefinitionName=='Website Contributor'].id" -o tsv }
if (-not $existing) {
    # O service principal recém-criado pode levar alguns segundos para ser visto pelo Azure RBAC.
    for ($i = 1; $i -le 6; $i++) {
        Invoke-Soft { az role assignment create --assignee-object-id $sp.id --assignee-principal-type ServicePrincipal --role 'Website Contributor' --scope $webAppId -o none }
        if ($LASTEXITCODE -eq 0) { break }
        $existing = Invoke-Soft { az role assignment list --scope $webAppId --query "[?principalId=='$($sp.id)' && roleDefinitionName=='Website Contributor'].id" -o tsv }
        if ($existing) { break }  # já existia (criação concorrente/propagação)
        if ($i -eq 6) { throw 'Falha ao atribuir o papel Website Contributor (verifique se você é Owner ou User Access Administrator no Resource Group).' }
        Start-Sleep -Seconds 10
    }
}

# ------------------------------------------------------------------ GitHub
Write-Host "Configurando o ambiente '$Environment' no GitHub..."
# Os dois ambientes só aceitam a branch main: publicar é executar código com os privilégios
# da aplicação, então uma branch qualquer não pode obter o token OIDC deste ambiente.
$politica = @{ protected_branches = $false; custom_branch_policies = $true }
$protegido = $true
function Set-GitHubEnvironment([hashtable] $Body) {
    $tmpEnv = Join-Path ([IO.Path]::GetTempPath()) "ghenv-$([guid]::NewGuid()).json"
    $Body | ConvertTo-Json -Depth 5 | Set-Content -Path $tmpEnv -Encoding ASCII
    try { Invoke-Soft { gh api -X PUT "repos/$Repository/environments/$Environment" --input $tmpEnv } | Out-Null }
    finally { Remove-Item $tmpEnv -ErrorAction SilentlyContinue }
    return ($LASTEXITCODE -eq 0)
}
$body = @{ deployment_branch_policy = $politica }
if ($Environment -eq 'production') {
    $me = gh api user --jq .id
    $body.reviewers = @(@{ type = 'User'; id = [int64]$me })
}
if (-not (Set-GitHubEnvironment $body)) {
    if ($Environment -ne 'production') {
        throw "Falha ao criar o ambiente '$Environment' no GitHub (em repositórios privados, ambientes exigem GitHub Pro/Team/Enterprise)."
    }
    Write-Host '  ! O GitHub recusou a aprovação obrigatória (em repositório privado ela exige GitHub Enterprise). Mantendo só a restrição à branch main.' -ForegroundColor Yellow
    $protegido = $false
    if (-not (Set-GitHubEnvironment @{ deployment_branch_policy = $politica })) { throw "Falha ao criar o ambiente '$Environment' no GitHub." }
}
$pol = Invoke-Soft { gh api "repos/$Repository/environments/$Environment/deployment-branch-policies" --jq '.branch_policies[].name' }
if (-not (@($pol) -contains 'main')) {
    Invoke-Soft { gh api -X POST "repos/$Repository/environments/$Environment/deployment-branch-policies" -f name=main -f type=branch } | Out-Null
    $pol = Invoke-Soft { gh api "repos/$Repository/environments/$Environment/deployment-branch-policies" --jq '.branch_policies[].name' }
    if (-not (@($pol) -contains 'main')) { throw "Não foi possível restringir o ambiente '$Environment' à branch main. O deploy NÃO foi habilitado." }
}

$vars = [ordered]@{
    AZURE_CLIENT_ID       = $app.appId
    AZURE_TENANT_ID       = $tenantId
    AZURE_SUBSCRIPTION_ID = $subscriptionId
    AZURE_RESOURCE_GROUP  = $rg
    AZURE_WEBAPP_NAME     = $webApp
}
foreach ($k in $vars.Keys) {
    gh variable set $k --env $Environment --body $vars[$k] --repo $Repository
    if ($LASTEXITCODE -ne 0) { throw "Falha ao gravar a variável $k no GitHub." }
}
if ($Environment -eq 'production' -and -not $protegido -and -not $AllowUnprotectedProduction) {
    Write-Host "`nProdução NÃO foi habilitada: sem aprovação obrigatória, qualquer execução na main publicaria direto." -ForegroundColor Yellow
    Write-Host 'Se aceitar esse risco, rode de novo com -AllowUnprotectedProduction.' -ForegroundColor Yellow
    return
}
gh variable set "DEPLOY_$($Environment.ToUpper())_ENABLED" --body 'true' --repo $Repository
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gravar a variável do repositório.' }

Write-Host "`nPronto. Identidade: $appName (client id $($app.appId)) — sem segredo." -ForegroundColor Green
if ($Environment -eq 'lab') {
    Write-Host "O próximo push na main publica automaticamente no ambiente 'lab'."
} else {
    Write-Host "Produção só é publicada manualmente (Actions → Deploy → Run workflow → production) e exige aprovação."
}
Write-Host "Para publicar agora: gh workflow run Deploy --repo $Repository -f ambiente=$Environment"
Write-Host "Acompanhe em: https://github.com/$Repository/actions"
Write-Host 'Obs.: a permissão no Azure pode levar alguns minutos para valer; se o primeiro deploy falhar no login, rode de novo.' -ForegroundColor DarkGray
