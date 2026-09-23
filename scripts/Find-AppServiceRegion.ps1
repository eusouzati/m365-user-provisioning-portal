<#
.SYNOPSIS
  Testa (sem criar nada) em quais regiões a assinatura tem cota para o App Service Plan.

.EXAMPLE
  ./scripts/Find-AppServiceRegion.ps1
  ./scripts/Find-AppServiceRegion.ps1 -Sku B1 -Regions brazilsouth,eastus2
#>
[CmdletBinding()]
param(
    [ValidateSet('F1', 'B1', 'B2', 'S1', 'P0v3', 'P1v3')] [string] $Sku = 'F1',
    [string[]] $Regions = @('brazilsouth', 'eastus', 'eastus2', 'centralus', 'westus2', 'westus3', 'southcentralus', 'canadacentral', 'northeurope', 'westeurope', 'uksouth')
)
$ErrorActionPreference = 'Stop'
$subTemplate = Join-Path ([IO.Path]::GetTempPath()) 'm365up-quota-check-sub.json'
@'
{
  "$schema": "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentTemplate.json#",
  "contentVersion": "1.0.0.0",
  "parameters": { "sku": { "type": "string" }, "region": { "type": "string" } },
  "resources": [
    { "type": "Microsoft.Resources/resourceGroups", "apiVersion": "2024-03-01", "name": "rg-m365up-quota-check", "location": "[parameters('region')]" },
    { "type": "Microsoft.Resources/deployments", "apiVersion": "2022-09-01", "name": "quota-check",
      "resourceGroup": "rg-m365up-quota-check",
      "dependsOn": [ "[subscriptionResourceId('Microsoft.Resources/resourceGroups', 'rg-m365up-quota-check')]" ],
      "properties": { "mode": "Incremental", "expressionEvaluationOptions": { "scope": "inner" },
        "parameters": { "sku": { "value": "[parameters('sku')]" }, "region": { "value": "[parameters('region')]" } },
        "template": {
          "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
          "contentVersion": "1.0.0.0",
          "parameters": { "sku": { "type": "string" }, "region": { "type": "string" } },
          "resources": [ { "type": "Microsoft.Web/serverfarms", "apiVersion": "2023-12-01", "name": "asp-quota-check",
            "location": "[parameters('region')]", "kind": "linux", "sku": { "name": "[parameters('sku')]" }, "properties": { "reserved": true } } ]
        } } }
  ]
}
'@ | Set-Content -Path $subTemplate -Encoding UTF8

Write-Host "Testando cota do plano $Sku (somente validação — nada é criado)...`n"
$ok = @()
foreach ($r in $Regions) {
    $out = az deployment sub validate --location $r --template-file $subTemplate --parameters sku=$Sku region=$r -o none 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host ("  {0,-16} OK" -f $r) -ForegroundColor Green; $ok += $r }
    elseif ("$out" -match 'OverQuota|quota') { Write-Host ("  {0,-16} sem cota" -f $r) -ForegroundColor Yellow }
    else { Write-Host ("  {0,-16} erro: {1}" -f $r, (("$out" -split "`n")[0])) -ForegroundColor Red }
}
Remove-Item $subTemplate -ErrorAction SilentlyContinue
if ($ok) { Write-Host "`nRegiões com cota: $($ok -join ', ')" -ForegroundColor Green }
else { Write-Host "`nNenhuma região com cota para $Sku. Solicite cota ou converta a assinatura para pay-as-you-go." -ForegroundColor Yellow }
