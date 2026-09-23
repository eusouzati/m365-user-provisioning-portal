#Requires -Version 7.0
<#
.SYNOPSIS
  Cria/atualiza a infraestrutura Azure do portal (Bicep, escopo de assinatura).

.DESCRIPTION
  1. Lê o .env e confere se o Azure CLI está no tenant/subscription corretos.
  2. Executa "what-if" e mostra o que será criado/alterado.
  3. Só aplica após você digitar SIM.
  4. Salva as saídas em infra-outputs.<ambiente>.json (ignorado pelo Git).
  Nunca exclui recursos (modo Incremental).

.EXAMPLE
  ./scripts/Deploy-Infrastructure.ps1 -Environment lab
  ./scripts/Deploy-Infrastructure.ps1 -Environment lab -WhatIfOnly
#>
[CmdletBinding()]
param(
    [ValidateSet('lab', 'production')] [string] $Environment = 'lab',
    [string] $EnvFile = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env'),
    [ValidateSet('F1', 'B1', 'B2', 'S1', 'P0v3', 'P1v3')] [string] $AppServiceSku,
    [switch] $WhatIfOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Common.ps1"

$cfg = Import-DotEnv $EnvFile
$tenantId = Get-Required $cfg 'AZURE_TENANT_ID'
$subscriptionId = Get-Required $cfg 'AZURE_SUBSCRIPTION_ID'
$location = Get-Required $cfg 'AZURE_LOCATION'
$prefix = Get-Required $cfg 'RESOURCE_PREFIX'
if (-not $AppServiceSku) { $AppServiceSku = if ($Environment -eq 'production') { 'B1' } else { 'F1' } }

Assert-AzureContext -TenantId $tenantId -SubscriptionId $subscriptionId
az bicep version *> $null
if ($LASTEXITCODE -ne 0) { throw 'Bicep CLI não encontrado. Rode: az bicep install' }

$template = Join-Path (Split-Path $PSScriptRoot -Parent) 'infra/main.bicep'
$deploymentName = "$prefix-$Environment-$(Get-Date -Format 'yyyyMMddHHmmss')"
$common = @(
    '--location', $location,
    '--template-file', $template,
    '--parameters',
    "environment=$Environment",
    "location=$location",
    "prefix=$prefix",
    "appServiceSku=$AppServiceSku",
    "m365DefaultDomain=$($cfg['M365_DEFAULT_DOMAIN'])",
    "usageLocation=$(if ($cfg['M365_DEFAULT_USAGE_LOCATION']) { $cfg['M365_DEFAULT_USAGE_LOCATION'] } else { 'BR' })",
    "timezone=$(if ($cfg['TIMEZONE']) { $cfg['TIMEZONE'] } else { 'America/Sao_Paulo' })"
)

Write-Host "`n== Pré-visualização (what-if) — rg-$prefix-$Environment / $location / plano $AppServiceSku ==" -ForegroundColor Cyan
az deployment sub what-if --name $deploymentName @common
if ($LASTEXITCODE -ne 0) { throw 'Falha no what-if.' }
if ($WhatIfOnly) { Write-Host "`nSomente pré-visualização. Nada foi criado." -ForegroundColor Yellow; return }

$answer = Read-Host "`nDigite SIM para aplicar estas mudanças"
if ($answer -cne 'SIM') { Write-Host 'Cancelado. Nada foi criado.' -ForegroundColor Yellow; return }

Write-Host "`n== Aplicando ($deploymentName) ==" -ForegroundColor Cyan
$result = az deployment sub create --name $deploymentName @common -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $result) { throw 'Falha na implantação. Veja os detalhes acima.' }

$outputs = [ordered]@{}
foreach ($p in $result.properties.outputs.PSObject.Properties) { $outputs[$p.Name] = $p.Value.value }
$outputs | ConvertTo-Json | Set-Content -Path (Get-OutputsPath $Environment) -Encoding UTF8

Write-Host "`nInfraestrutura pronta:" -ForegroundColor Green
$outputs.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-28} {1}" -f $_.Key, $_.Value) }
Write-Host "`nPróximo passo: ./scripts/Deploy-Application.ps1 -Environment $Environment"
