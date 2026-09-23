<#
.SYNOPSIS
  Empacota e publica a aplicação no Azure App Service e valida o /health.

.EXAMPLE
  ./scripts/Deploy-Application.ps1 -Environment lab
#>
[CmdletBinding()]
param(
    [ValidateSet('lab', 'production')] [string] $Environment = 'lab',
    [string] $EnvFile = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env'),
    [int] $HealthTimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Common.ps1"

$cfg = Import-DotEnv $EnvFile
Assert-AzureContext -TenantId (Get-Required $cfg 'AZURE_TENANT_ID') -SubscriptionId (Get-Required $cfg 'AZURE_SUBSCRIPTION_ID')

$outputsPath = Get-OutputsPath $Environment
if (-not (Test-Path $outputsPath)) { throw "Saídas da infraestrutura não encontradas ($outputsPath). Rode Deploy-Infrastructure.ps1 antes." }
$out = Get-Content $outputsPath -Raw | ConvertFrom-Json

$root = Split-Path $PSScriptRoot -Parent
$zip = Join-Path ([IO.Path]::GetTempPath()) "m365up-$Environment-$(Get-Date -Format 'yyyyMMddHHmmss').zip"
Assert-Command tar 'O tar vem com o Windows 10+.'
Push-Location $root
try {
    # tar gera ZIP com separador "/" (compatível com Linux)
    tar -a -c -f $zip --exclude '__pycache__' --exclude '*.pyc' app requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o pacote.' }
} finally { Pop-Location }
Write-Host "Pacote: $zip ($([math]::Round((Get-Item $zip).Length / 1KB)) KB)"

Write-Host "`n== Publicando em $($out.webAppName) ==" -ForegroundColor Cyan
az webapp deploy --resource-group $out.resourceGroupName --name $out.webAppName --src-path $zip --type zip --track-status false
if ($LASTEXITCODE -ne 0) { throw 'Falha no deploy.' }
Remove-Item $zip -ErrorAction SilentlyContinue

Write-Host "`nAguardando a aplicação responder (o primeiro build no plano F1 pode levar alguns minutos)..."
$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
$url = "$($out.webAppUrl)/health"
do {
    try {
        $resp = Invoke-RestMethod -Uri $url -TimeoutSec 30
        if ($resp.status -eq 'healthy') {
            Write-Host "OK  $url -> $($resp | ConvertTo-Json -Compress)" -ForegroundColor Green
            try {
                $ready = Invoke-RestMethod -Uri "$($out.webAppUrl)/health/ready" -TimeoutSec 30
                Write-Host "OK  /health/ready -> $($ready | ConvertTo-Json -Compress)" -ForegroundColor Green
            } catch { Write-Warning "/health/ready falhou: $($_.Exception.Message) (verifique as permissões da Managed Identity no Storage; podem levar alguns minutos para propagar)" }
            return
        }
    } catch { Write-Host '  ...ainda não respondeu' -ForegroundColor DarkGray }
    Start-Sleep -Seconds 15
} while ((Get-Date) -lt $deadline)
throw "A aplicação não respondeu em $HealthTimeoutSeconds s. Veja os logs: az webapp log tail -g $($out.resourceGroupName) -n $($out.webAppName)"
