<#
.SYNOPSIS
  Concede à Managed Identity do portal as permissões de APLICAÇÃO do Microsoft Graph,
  por nível, com pré-visualização e confirmação.

.DESCRIPTION
  Nível "leitura" (Sprint 3) — somente leitura, nenhuma alteração possível no M365:
    User.Read.All                     buscar usuários/gestores, verificar UPN e aliases
    Group.Read.All                    listar grupos e licenças atribuídas a grupos
    Organization.Read.All             organização e licenças (subscribedSkus)
    Domain.Read.All                   domínios verificados
    Policy.Read.AuthenticationMethod  política de Temporary Access Pass

  Níveis de escrita serão adicionados nas Sprints 6 a 8, um a um, com a mesma confirmação.
  Idempotente e nunca remove permissões (permissões extras são apenas listadas).

  Permissões delegadas do operador (Administrador Global ou Administrador de Funções Privilegiadas):
    AppRoleAssignment.ReadWrite.All, Application.Read.All

.EXAMPLE
  ./scripts/Set-GraphPermissions.ps1 -Environment lab -WhatIfOnly
  ./scripts/Set-GraphPermissions.ps1 -Environment lab
#>
[CmdletBinding()]
param(
    [ValidateSet('lab', 'production')] [string] $Environment = 'lab',
    [ValidateSet('leitura')] [string] $Nivel = 'leitura',
    [string] $EnvFile = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env'),
    [switch] $WhatIfOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Common.ps1"
Set-StrictMode -Off

$niveis = [ordered]@{
    leitura = @(
        'User.Read.All'
        'Group.Read.All'
        'Organization.Read.All'
        'Domain.Read.All'
        'Policy.Read.AuthenticationMethod'
    )
}
$desejadas = $niveis[$Nivel]

$cfg = Import-DotEnv $EnvFile
$tenantId = Get-Required $cfg 'AZURE_TENANT_ID'
$outputsPath = Get-OutputsPath $Environment
if (-not (Test-Path $outputsPath)) { throw "Saídas da infraestrutura não encontradas ($outputsPath)." }
$infra = Get-Content $outputsPath -Raw | ConvertFrom-Json
$miPrincipalId = $infra.managedIdentityPrincipalId

if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication)) {
    throw 'Instale o módulo: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser'
}
Import-Module Microsoft.Graph.Authentication

function G([string] $Method = 'GET', [string] $Uri, $Body) {
    $p = @{ Method = $Method; Uri = $Uri; OutputType = 'PSObject' }
    if ($null -ne $Body) { $p.Body = ($Body | ConvertTo-Json -Depth 5); $p.ContentType = 'application/json' }
    Invoke-MgGraphRequest @p
}

Write-Host "`n== Conectando ao Microsoft Graph (tenant $tenantId) ==" -ForegroundColor Cyan
Connect-MgGraph -TenantId $tenantId -NoWelcome -ContextScope Process -Scopes 'AppRoleAssignment.ReadWrite.All', 'Application.Read.All'
$ctx = Get-MgContext
if ($ctx.TenantId -ne $tenantId) { throw "Conectado ao tenant $($ctx.TenantId), esperado $tenantId. Abortando." }

$graphSp = @((G -Uri "v1.0/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appRoles").value)[0]
$miSp = G -Uri "v1.0/servicePrincipals/$($miPrincipalId)?`$select=id,displayName"
$atuais = @((G -Uri "v1.0/servicePrincipals/$($miSp.id)/appRoleAssignments").value) |
    Where-Object { $_.resourceId -eq $graphSp.id }
$rolePorValor = @{}; $valorPorRole = @{}
foreach ($r in $graphSp.appRoles) { $rolePorValor[$r.value] = $r.id; $valorPorRole[$r.id] = $r.value }
$atuaisValores = @($atuais | ForEach-Object { $valorPorRole[$_.appRoleId] })

Write-Host "`n== Plano — Managed Identity '$($miSp.displayName)' ($($miSp.id)) · nível '$Nivel' ==" -ForegroundColor Cyan
$faltando = @()
foreach ($p in $desejadas) {
    if (-not $rolePorValor.ContainsKey($p)) { throw "Permissão '$p' não encontrada no Microsoft Graph." }
    if ($atuaisValores -contains $p) { Write-Host "  = $p (já concedida)" -ForegroundColor DarkGray }
    else { Write-Host "  + $p" -ForegroundColor Green; $faltando += $p }
}
$extras = @($atuaisValores | Where-Object { $_ -and ($desejadas -notcontains $_) })
foreach ($e in $extras) { Write-Host "  ! $e (concedida, fora deste nível — não será removida)" -ForegroundColor Yellow }
Write-Host "`nSomente permissões de leitura. Nada será removido."

if (-not $faltando) { Write-Host "`nNada a fazer." -ForegroundColor Green; Disconnect-MgGraph | Out-Null; return }
if ($WhatIfOnly) { Write-Host "`nSomente pré-visualização. Nada foi alterado." -ForegroundColor Yellow; Disconnect-MgGraph | Out-Null; return }
if ((Read-Host "`nDigite SIM para conceder") -cne 'SIM') { Write-Host 'Cancelado. Nada foi alterado.' -ForegroundColor Yellow; return }

foreach ($p in $faltando) {
    G -Method POST -Uri "v1.0/servicePrincipals/$($miSp.id)/appRoleAssignments" -Body ([ordered]@{
            principalId = $miSp.id; resourceId = $graphSp.id; appRoleId = $rolePorValor[$p]
        }) | Out-Null
    Write-Host "  Concedida: $p" -ForegroundColor Green
}
Disconnect-MgGraph | Out-Null
Write-Host "`nPronto. As permissões podem levar alguns minutos para valer (o token da Managed Identity fica em cache por até 24 h;"
Write-Host "se a página de capacidades mostrar erro de permissão, reinicie o App Service: az webapp restart -g $($infra.resourceGroupName) -n $($infra.webAppName))."
