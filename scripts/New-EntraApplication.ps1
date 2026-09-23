<#
.SYNOPSIS
  Cria/atualiza o App Registration do portal, os App Roles, os grupos dos papéis e a
  credencial federada com a Managed Identity (login sem Client Secret).

.DESCRIPTION
  Idempotente: pode ser executado novamente; reaproveita o que já existe.
  Nunca exclui nada. Mostra o plano e só aplica após você digitar SIM.

  Cria/garante:
    - App Registration "<prefixo>-portal-<ambiente>" (somente este tenant)
    - App Roles: Provisionamento.Solicitante / .Aprovador / .Administrador
    - Enterprise Application (service principal)
    - (somente -AuthFlow fic) Credencial federada: Managed Identity do App Service -> App Registration
    - Grupos de segurança <PREFIXO>-Solicitantes-RH / -Aprovadores / -Administradores
    - Atribuição de cada App Role ao seu grupo (requer Entra ID P1 ou superior)
  Ao final grava ENTRA_APP_CLIENT_ID no .env e salva entra-outputs.<ambiente>.json.

  Permissões delegadas usadas (entrar como Administrador Global ou Administrador de
  Aplicativos + Administrador de Grupos):
    Application.ReadWrite.All, AppRoleAssignment.ReadWrite.All, Group.ReadWrite.All, User.Read

.EXAMPLE
  ./scripts/New-EntraApplication.ps1 -Environment lab -WhatIfOnly
  ./scripts/New-EntraApplication.ps1 -Environment lab -AddMeToGroups Administradores,Solicitantes,Aprovadores
#>
[CmdletBinding()]
param(
    [ValidateSet('lab', 'production')] [string] $Environment = 'lab',
    [string] $EnvFile = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env'),
    [ValidateSet('Solicitantes', 'Aprovadores', 'Administradores')] [string[]] $AddMeToGroups = @(),
    # idtoken: fluxo de ID token do App Service (GA, sem segredo) · fic: Managed Identity como credencial federada (preview)
    [ValidateSet('idtoken', 'fic')] [string] $AuthFlow = 'idtoken',
    [switch] $WhatIfOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Common.ps1"
# Respostas do Graph têm propriedades opcionais; o modo estrito quebraria o acesso a elas.
Set-StrictMode -Off

$root = Split-Path $PSScriptRoot -Parent
$cfg = Import-DotEnv $EnvFile
$tenantId = Get-Required $cfg 'AZURE_TENANT_ID'
$prefix = Get-Required $cfg 'RESOURCE_PREFIX'

$outputsPath = Get-OutputsPath $Environment
if (-not (Test-Path $outputsPath)) { throw "Saídas da infraestrutura não encontradas ($outputsPath). Rode Deploy-Infrastructure.ps1 antes." }
$infra = Get-Content $outputsPath -Raw | ConvertFrom-Json
$webAppUrl = $infra.webAppUrl.TrimEnd('/')
$miPrincipalId = $infra.managedIdentityPrincipalId
$miName = $infra.managedIdentityName

if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication)) {
    throw 'Instale o módulo: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser'
}
Import-Module Microsoft.Graph.Authentication

$appName = "$prefix-portal-$Environment"
$groupPrefix = $prefix.ToUpper()
$redirectUri = "$webAppUrl/.auth/login/aad/callback"
$ficName = "managed-identity-$miName"
$ficIssuer = "https://login.microsoftonline.com/$tenantId/v2.0"
$graphAppId = '00000003-0000-0000-c000-000000000000'
$userReadScope = 'e1fe6dd8-ba31-4d61-89e7-88639da4683d'

$roleDefs = @(
    [ordered]@{ key = 'Solicitantes'; value = 'Provisionamento.Solicitante'; displayName = 'Solicitante (RH)'
        description = 'Cria solicitações de entrada e saída de colaboradores.'; group = "$groupPrefix-Solicitantes-RH" }
    [ordered]@{ key = 'Aprovadores'; value = 'Provisionamento.Aprovador'; displayName = 'Aprovador'
        description = 'Aprova ou rejeita solicitações do RH.'; group = "$groupPrefix-Aprovadores" }
    [ordered]@{ key = 'Administradores'; value = 'Provisionamento.Administrador'; displayName = 'Administrador'
        description = 'Configura perfis, grupos, licenças e consulta a auditoria.'; group = "$groupPrefix-Administradores" }
)

function Invoke-Graph {
    param([string] $Method = 'GET', [string] $Uri, $Body, [int] $Retries = 6)
    for ($i = 1; ; $i++) {
        try {
            $p = @{ Method = $Method; Uri = $Uri; OutputType = 'PSObject' }
            if ($null -ne $Body) { $p.Body = ($Body | ConvertTo-Json -Depth 10); $p.ContentType = 'application/json' }
            return Invoke-MgGraphRequest @p
        } catch {
            $msg = "$($_.Exception.Message) $($_.ErrorDetails.Message)"
            # Replicação do diretório: objetos recém-criados podem demorar alguns segundos
            if ($i -lt $Retries -and $msg -match 'does not exist|Request_ResourceNotFound|NotFound|404') {
                Start-Sleep -Seconds (5 * $i); continue
            }
            throw
        }
    }
}
function Get-Single([string] $Uri) { $r = Invoke-Graph -Uri $Uri; if ($r.value) { return @($r.value)[0] } return $null }
function Esc([string] $s) { return $s.Replace("'", "''") }

Write-Host "`n== Conectando ao Microsoft Graph (tenant $tenantId) ==" -ForegroundColor Cyan
Connect-MgGraph -TenantId $tenantId -NoWelcome -ContextScope Process `
    -Scopes 'Application.ReadWrite.All', 'AppRoleAssignment.ReadWrite.All', 'Group.ReadWrite.All', 'User.Read'
$ctx = Get-MgContext
if ($ctx.TenantId -ne $tenantId) { throw "Conectado ao tenant $($ctx.TenantId), esperado $tenantId. Abortando." }
Write-Host "Conectado como $($ctx.Account)" -ForegroundColor DarkGray

# ---------- Descoberta ----------
$app = Get-Single "v1.0/applications?`$filter=displayName eq '$(Esc $appName)'"
$sp = if ($app) { Get-Single "v1.0/servicePrincipals?`$filter=appId eq '$($app.appId)'" } else { $null }
$fic = $null
if ($app) {
    $fic = @((Invoke-Graph -Uri "v1.0/applications/$($app.id)/federatedIdentityCredentials").value) |
        Where-Object { $_.subject -eq $miPrincipalId } | Select-Object -First 1
}
$groups = @{}
foreach ($r in $roleDefs) { $groups[$r.key] = Get-Single "v1.0/groups?`$filter=displayName eq '$(Esc $r.group)'" }

function Show-Item([string] $what, $exists) {
    if ($exists) { Write-Host "  = $what (já existe)" -ForegroundColor DarkGray } else { Write-Host "  + $what" -ForegroundColor Green }
}
Write-Host "`n== Plano ==" -ForegroundColor Cyan
Show-Item "App Registration '$appName' (somente este tenant; redirect $redirectUri)" $app
if ($app) { Write-Host "  ~ Garantir App Roles, redirect URI e permissões do App Registration" -ForegroundColor Yellow }
Show-Item "Enterprise Application (service principal)" $sp
if ($AuthFlow -eq 'fic') { Show-Item "Credencial federada '$ficName' (Managed Identity $miPrincipalId)" $fic }
else { Write-Host "  ~ Fluxo de login: ID token (emissão de ID token habilitada no App Registration; sem segredo)" -ForegroundColor Yellow }
foreach ($r in $roleDefs) { Show-Item "Grupo de segurança '$($r.group)' -> App Role $($r.value)" $groups[$r.key] }
foreach ($g in $AddMeToGroups) { Write-Host "  + Adicionar $($ctx.Account) ao grupo de $g (se ainda não for membro)" -ForegroundColor Green }
Write-Host "  ~ Gravar ENTRA_APP_CLIENT_ID no .env e salvar entra-outputs.$Environment.json" -ForegroundColor Yellow
Write-Host "`nNada será excluído."

if ($WhatIfOnly) { Write-Host "`nSomente pré-visualização. Nada foi alterado." -ForegroundColor Yellow; return }
if ((Read-Host "`nDigite SIM para aplicar") -cne 'SIM') { Write-Host 'Cancelado. Nada foi alterado.' -ForegroundColor Yellow; return }

# ---------- App Registration ----------
$existingRoles = @()
if ($app -and $app.appRoles) { $existingRoles = @($app.appRoles) }
$appRoles = @($existingRoles | ForEach-Object {
        [ordered]@{ id = $_.id; allowedMemberTypes = @($_.allowedMemberTypes); displayName = $_.displayName
            description = $_.description; value = $_.value; isEnabled = $_.isEnabled } })
foreach ($r in $roleDefs) {
    if (-not ($appRoles | Where-Object { $_.value -eq $r.value })) {
        $appRoles += [ordered]@{ id = [guid]::NewGuid().ToString(); allowedMemberTypes = @('User'); displayName = $r.displayName
            description = $r.description; value = $r.value; isEnabled = $true }
    }
}
$redirects = @($redirectUri)
if ($app -and $app.web -and $app.web.redirectUris) { $redirects = @(@($app.web.redirectUris) + $redirectUri | Select-Object -Unique) }

$appBody = [ordered]@{
    displayName            = $appName
    signInAudience         = 'AzureADMyOrg'
    notes                  = 'Portal de Provisionamento M365 (open source). Login via App Service Authentication com credencial federada de Managed Identity — sem Client Secret.'
    web                    = [ordered]@{
        homePageUrl           = $webAppUrl
        logoutUrl             = "$webAppUrl/.auth/logout"
        redirectUris          = $redirects
        implicitGrantSettings = [ordered]@{ enableIdTokenIssuance = ($AuthFlow -eq 'idtoken'); enableAccessTokenIssuance = $false }
    }
    appRoles               = $appRoles
    requiredResourceAccess = @([ordered]@{ resourceAppId = $graphAppId; resourceAccess = @([ordered]@{ id = $userReadScope; type = 'Scope' }) })
}

if (-not $app) {
    Write-Host "`nCriando App Registration..." -ForegroundColor Cyan
    $app = Invoke-Graph -Method POST -Uri 'v1.0/applications' -Body $appBody
} else {
    Write-Host "`nAtualizando App Registration..." -ForegroundColor Cyan
    Invoke-Graph -Method PATCH -Uri "v1.0/applications/$($app.id)" -Body $appBody | Out-Null
    $app = Invoke-Graph -Uri "v1.0/applications/$($app.id)"
}
Write-Host "  Client ID: $($app.appId)"

# ---------- Service principal ----------
if (-not $sp) {
    Write-Host 'Criando Enterprise Application...' -ForegroundColor Cyan
    $sp = Invoke-Graph -Method POST -Uri 'v1.0/servicePrincipals' -Body ([ordered]@{
            appId = $app.appId; appRoleAssignmentRequired = $false
            tags  = @('WindowsAzureActiveDirectoryIntegratedApp')
        })
}

# ---------- Credencial federada ----------
if ($AuthFlow -eq 'fic' -and -not $fic) {
    Write-Host 'Criando credencial federada com a Managed Identity...' -ForegroundColor Cyan
    Invoke-Graph -Method POST -Uri "v1.0/applications/$($app.id)/federatedIdentityCredentials" -Body ([ordered]@{
            name        = $ficName
            issuer      = $ficIssuer
            subject     = $miPrincipalId
            audiences   = @('api://AzureADTokenExchange')
            description = 'Permite ao App Service Authentication usar a Managed Identity em vez de Client Secret.'
        }) | Out-Null
}

# ---------- Grupos + atribuição de App Roles ----------
$assigned = @((Invoke-Graph -Uri "v1.0/servicePrincipals/$($sp.id)/appRoleAssignedTo?`$top=999").value)
$roleIds = @{}
foreach ($ar in $app.appRoles) { $roleIds[$ar.value] = $ar.id }

foreach ($r in $roleDefs) {
    $g = $groups[$r.key]
    if (-not $g) {
        Write-Host "Criando grupo $($r.group)..." -ForegroundColor Cyan
        $nick = ($r.group -replace '[^A-Za-z0-9-]', '').ToLower()
        $g = Invoke-Graph -Method POST -Uri 'v1.0/groups' -Body ([ordered]@{
                displayName = $r.group; mailEnabled = $false; mailNickname = $nick; securityEnabled = $true
                description = "Portal de Provisionamento M365 — membros recebem o papel $($r.displayName)."
            })
        $groups[$r.key] = $g
    }
    $roleId = $roleIds[$r.value]
    if (-not ($assigned | Where-Object { $_.principalId -eq $g.id -and $_.appRoleId -eq $roleId })) {
        Write-Host "  Atribuindo papel $($r.value) ao grupo $($r.group)..."
        try {
            Invoke-Graph -Method POST -Uri "v1.0/servicePrincipals/$($sp.id)/appRoleAssignedTo" -Body ([ordered]@{
                    principalId = $g.id; resourceId = $sp.id; appRoleId = $roleId
                }) | Out-Null
        } catch {
            Write-Warning "Falha ao atribuir o papel ao grupo (atribuição de grupos a aplicativos exige Entra ID P1+): $($_.Exception.Message)"
        }
    }
}

# ---------- Adicionar o usuário atual ----------
if ($AddMeToGroups.Count -gt 0) {
    $me = Invoke-Graph -Uri 'v1.0/me?$select=id,userPrincipalName'
    foreach ($key in $AddMeToGroups) {
        $g = $groups[$key]
        try {
            Invoke-Graph -Method POST -Uri "v1.0/groups/$($g.id)/members/`$ref" -Body @{ '@odata.id' = "https://graph.microsoft.com/v1.0/directoryObjects/$($me.id)" } | Out-Null
            Write-Host "  $($me.userPrincipalName) adicionado a $($g.displayName)"
        } catch {
            if ("$($_.Exception.Message) $($_.ErrorDetails.Message)" -match 'already exist') { Write-Host "  $($me.userPrincipalName) já é membro de $($g.displayName)" -ForegroundColor DarkGray }
            else { throw }
        }
    }
}

# ---------- Saídas ----------
$out = [ordered]@{
    appName = $appName; clientId = $app.appId; applicationObjectId = $app.id; servicePrincipalId = $sp.id
    grupos  = [ordered]@{}
}
foreach ($r in $roleDefs) { $out.grupos[$r.value] = [ordered]@{ nome = $groups[$r.key].displayName; id = $groups[$r.key].id } }
$out | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $root "entra-outputs.$Environment.json") -Encoding UTF8

$lines = @(Get-Content $EnvFile -Encoding UTF8)
if ($lines -match '^\s*ENTRA_APP_CLIENT_ID\s*=') { $lines = $lines -replace '^\s*ENTRA_APP_CLIENT_ID\s*=.*$', "ENTRA_APP_CLIENT_ID=$($app.appId)" }
else { $lines += "ENTRA_APP_CLIENT_ID=$($app.appId)" }
if ($lines -match '^\s*ENTRA_AUTH_FLOW\s*=') { $lines = $lines -replace '^\s*ENTRA_AUTH_FLOW\s*=.*$', "ENTRA_AUTH_FLOW=$AuthFlow" }
else { $lines += "ENTRA_AUTH_FLOW=$AuthFlow" }
$lines | Set-Content -Path $EnvFile -Encoding UTF8

Disconnect-MgGraph | Out-Null
Write-Host "`nPronto. ENTRA_APP_CLIENT_ID=$($app.appId) e ENTRA_AUTH_FLOW=$AuthFlow gravados no .env." -ForegroundColor Green
Write-Host 'Próximos passos (ativam o login no App Service):'
Write-Host "  ./scripts/Deploy-Infrastructure.ps1 -Environment $Environment"
Write-Host "  ./scripts/Deploy-Application.ps1 -Environment $Environment"
Write-Host "Observação: novos membros de grupo podem levar alguns minutos para receber o papel (saia e entre novamente)."
