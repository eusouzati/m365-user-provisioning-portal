<#
.SYNOPSIS
  Sprint 0 - Descoberta e validacao do ambiente (SOMENTE LEITURA).

.DESCRIPTION
  Verifica ferramentas locais, sessao Azure, GitHub CLI e o tenant via Microsoft Graph.
  Nao cria, altera nem exclui nada. Nao coleta senhas, tokens ou segredos.
  Gera o arquivo sprint0-report.json na mesma pasta deste script.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Test-Prerequisites.ps1 -TenantId <id>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $TenantId,
    [switch] $SkipGraph
)

$ErrorActionPreference = 'Continue'
$report = [ordered]@{
    geradoEm   = (Get-Date).ToString('s')
    tenantIdEsperado = $TenantId
    ferramentas = [ordered]@{}
    azure      = [ordered]@{}
    github     = [ordered]@{}
    graph      = [ordered]@{}
    alertas    = @()
}
function Add-Alerta($msg) { $script:report.alertas += $msg; Write-Host "  [ALERTA] $msg" -ForegroundColor Yellow }
function Get-Ver([string]$cmd, [string[]]$verArgs) {
    $c = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $c) { return $null }
    try { return ((& $cmd @verArgs 2>&1) | Select-Object -First 1).ToString().Trim() } catch { return 'instalado (versao nao lida)' }
}

Write-Host "`n== 1. Ferramentas locais ==" -ForegroundColor Cyan
$report.ferramentas.powershell = $PSVersionTable.PSVersion.ToString()
$report.ferramentas.pwsh7      = Get-Ver 'pwsh' @('--version')
$report.ferramentas.python     = Get-Ver 'python' @('--version')
$report.ferramentas.git        = Get-Ver 'git' @('--version')
$report.ferramentas.gh         = Get-Ver 'gh' @('--version')
$report.ferramentas.az         = $null
if (Get-Command az -ErrorAction SilentlyContinue) {
    try { $report.ferramentas.az = (az version -o json 2>$null | ConvertFrom-Json).'azure-cli' } catch {}
    try { $report.ferramentas.bicep = ((az bicep version 2>&1) | Select-Object -First 1).ToString().Trim() } catch {}
}
$report.ferramentas.func = Get-Ver 'func' @('--version')
$mg = Get-Module -ListAvailable Microsoft.Graph.Authentication | Sort-Object Version -Descending | Select-Object -First 1
$report.ferramentas.graphPowerShellSdk = if ($mg) { $mg.Version.ToString() } else { $null }
$report.ferramentas.GetEnumerator() | ForEach-Object {
    $v = if ($_.Value) { $_.Value } else { 'NAO ENCONTRADO' }
    Write-Host ("  {0,-20} {1}" -f $_.Key, $v)
}
# O Python da Microsoft Store (atalho) nao funciona de verdade
if ($report.ferramentas.python -and $report.ferramentas.python -notmatch 'Python 3\.(1[1-9]|[2-9]\d)') { Add-Alerta "Python 3.11+ recomendado (encontrado: $($report.ferramentas.python))" }

Write-Host "`n== 2. Azure ==" -ForegroundColor Cyan
if ($report.ferramentas.az) {
    $acct = $null
    try { $acct = az account show -o json 2>$null | ConvertFrom-Json } catch {}
    if (-not $acct) {
        Add-Alerta "Sem sessao Azure. Rode: az login --tenant $TenantId   e execute este script novamente."
    } else {
        $report.azure.usuario        = $acct.user.name
        $report.azure.tenantAtivo    = $acct.tenantId
        $report.azure.subscriptionId = $acct.id
        $report.azure.subscriptionNome = $acct.name
        $report.azure.estado         = $acct.state
        if ($acct.tenantId -ne $TenantId) { Add-Alerta "Tenant ativo no Azure CLI ($($acct.tenantId)) diferente do esperado ($TenantId). PARAR." }
        try {
            $report.azure.subscriptionsDisponiveis = @(az account list --all -o json 2>$null | ConvertFrom-Json |
                Select-Object name, id, tenantId, state, isDefault)
        } catch {}
        try {
            $sub = az rest --method get --url "https://management.azure.com/subscriptions/$($acct.id)?api-version=2022-12-01" -o json 2>$null | ConvertFrom-Json
            $report.azure.quotaId = $sub.subscriptionPolicies.quotaId
            $report.azure.spendingLimit = $sub.subscriptionPolicies.spendingLimit
        } catch {}
        $report.azure.providers = [ordered]@{}
        foreach ($ns in 'Microsoft.Web','Microsoft.Storage','Microsoft.KeyVault','Microsoft.Insights','Microsoft.OperationalInsights','Microsoft.ManagedIdentity') {
            try { $report.azure.providers[$ns] = (az provider show -n $ns --query registrationState -o tsv 2>$null) } catch {}
        }
        try { $report.azure.resourceGroups = @(az group list --query "[].{nome:name, regiao:location}" -o json 2>$null | ConvertFrom-Json) } catch {}
        Write-Host "  Usuario: $($report.azure.usuario)"
        Write-Host "  Subscription: $($report.azure.subscriptionNome) ($($report.azure.subscriptionId)) - $($report.azure.quotaId)"
    }
} else { Add-Alerta "Azure CLI nao encontrado." }

Write-Host "`n== 3. GitHub ==" -ForegroundColor Cyan
if ($report.ferramentas.gh) {
    try {
        $login = gh api user --jq .login 2>$null
        if ($LASTEXITCODE -eq 0 -and $login) {
            $report.github.usuario = $login
            try { $report.github.organizacoes = @(gh api user/orgs --jq '.[].login' 2>$null) } catch {}
            $existe = gh repo view "$login/m365-user-provisioning-portal" --json name 2>$null
            $report.github.repoSugeridoExiste = [bool]$existe
            Write-Host "  Autenticado como: $login"
        } else { Add-Alerta "GitHub CLI nao autenticado. Rode: gh auth login" }
    } catch { Add-Alerta "Falha ao consultar GitHub CLI." }
} else { Add-Alerta "GitHub CLI (gh) nao encontrado." }

Write-Host "`n== 4. Microsoft Graph (somente leitura) ==" -ForegroundColor Cyan
if ($SkipGraph) { Write-Host "  Ignorado (-SkipGraph)." }
elseif (-not $mg) { Add-Alerta "Microsoft Graph PowerShell SDK nao encontrado. Instale com: Install-Module Microsoft.Graph -Scope CurrentUser" }
else {
    try {
        Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
        Connect-MgGraph -TenantId $TenantId -NoWelcome -ContextScope Process `
            -Scopes 'Organization.Read.All','Directory.Read.All','Policy.Read.All' -ErrorAction Stop
        $ctx = Get-MgContext
        $report.graph.conectadoComo = $ctx.Account
        $report.graph.escopos = $ctx.Scopes

        $org = (Invoke-MgGraphRequest -Method GET -Uri 'v1.0/organization?$select=id,displayName,onPremisesSyncEnabled,countryLetterCode,preferredLanguage').value[0]
        $report.graph.organizacao = [ordered]@{
            nome = $org.displayName; tenantId = $org.id
            somenteNuvem = -not [bool]$org.onPremisesSyncEnabled
            pais = $org.countryLetterCode; idioma = $org.preferredLanguage
        }
        if ($org.onPremisesSyncEnabled) { Add-Alerta "Sincronizacao on-premises ATIVA - o projeto assume tenant somente nuvem." }

        $report.graph.dominios = @((Invoke-MgGraphRequest -Method GET -Uri 'v1.0/domains').value |
            ForEach-Object { [ordered]@{ nome = $_.id; padrao = $_.isDefault; verificado = $_.isVerified } })

        $skus = (Invoke-MgGraphRequest -Method GET -Uri 'v1.0/subscribedSkus').value
        $report.graph.licencas = @($skus | ForEach-Object {
            [ordered]@{
                skuPartNumber = $_.skuPartNumber; skuId = $_.skuId; status = $_.capabilityStatus
                total = $_.prepaidUnits.enabled; usadas = $_.consumedUnits
                disponiveis = ($_.prepaidUnits.enabled - $_.consumedUnits)
            } })
        $plans = @($skus | ForEach-Object { $_.servicePlans } | Where-Object { $_.provisioningStatus -eq 'Success' } | ForEach-Object { $_.servicePlanName })
        $report.graph.capacidades = [ordered]@{
            entraP1         = [bool]($plans -match '^AAD_PREMIUM$')
            entraP2         = [bool]($plans -match '^AAD_PREMIUM_P2$')
            entraGovernance = [bool]($plans -match 'GOVERNANCE|Entra_Identity_Governance|IDENTITY_GOVERNANCE')
            exchangeOnline  = [bool]($plans -match '^EXCHANGE_S_')
        }

        try {
            $tap = Invoke-MgGraphRequest -Method GET -Uri 'v1.0/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/TemporaryAccessPass'
            $report.graph.politicaTAP = [ordered]@{
                estado = $tap.state; duracaoPadraoMin = $tap.defaultLifetimeInMinutes
                duracaoMaxMin = $tap.maximumLifetimeInMinutes; usoUnicoPadrao = $tap.isUsableOnce
            }
            if ($tap.state -ne 'enabled') { Add-Alerta "Politica de Temporary Access Pass desabilitada (sera necessario habilitar antes da Sprint 7)." }
        } catch { Add-Alerta "Nao foi possivel ler a politica de TAP." }

        $groups = (Invoke-MgGraphRequest -Method GET -Uri 'v1.0/groups?$select=id,displayName,groupTypes,securityEnabled,mailEnabled,isAssignableToRole&$top=999').value
        $report.graph.grupos = @($groups | ForEach-Object {
            [ordered]@{ nome = $_.displayName; id = $_.id; seguranca = $_.securityEnabled
                        m365 = ($_.groupTypes -contains 'Unified'); atribuivelAFuncao = [bool]$_.isAssignableToRole } })

        $report.graph.qtdUsuarios = [int](Invoke-MgGraphRequest -Method GET -Uri 'v1.0/users/$count' -Headers @{ ConsistencyLevel = 'eventual' } -OutputType Json)
        $apps = (Invoke-MgGraphRequest -Method GET -Uri 'v1.0/applications?$select=appId,displayName,id').value
        $report.graph.appRegistrations = @($apps | ForEach-Object { [ordered]@{ nome = $_.displayName; clientId = $_.appId; objectId = $_.id } })

        Write-Host "  Organizacao: $($org.displayName) | somente nuvem: $(-not [bool]$org.onPremisesSyncEnabled)"
        Write-Host "  Capacidades: $($report.graph.capacidades | ConvertTo-Json -Compress)"
        Disconnect-MgGraph | Out-Null
    } catch { Add-Alerta "Falha no Microsoft Graph: $($_.Exception.Message)" }
}

$out = Join-Path $PSScriptRoot 'sprint0-report.json'
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $out -Encoding UTF8
Write-Host "`nRelatorio salvo em: $out" -ForegroundColor Green
Write-Host "Nenhuma alteracao foi feita no Azure, GitHub ou Microsoft 365."
