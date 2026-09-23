# Funções compartilhadas pelos scripts. Uso: . "$PSScriptRoot/Common.ps1"
Set-StrictMode -Version Latest

function Import-DotEnv {
    param([Parameter(Mandatory)] [string] $Path)
    if (-not (Test-Path $Path)) { throw "Arquivo de configuração não encontrado: $Path (copie .env.example para .env)" }
    $cfg = @{}
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $idx = $t.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $t.Substring(0, $idx).Trim()
        $val = ($t.Substring($idx + 1) -replace '\s+#.*$', '').Trim().Trim('"').Trim("'")
        $cfg[$key] = $val
    }
    return $cfg
}

function Get-Required {
    param([hashtable] $Config, [string] $Key)
    if (-not $Config.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace($Config[$Key])) {
        throw "Variável obrigatória ausente no .env: $Key"
    }
    return $Config[$Key]
}

function Assert-Command {
    param([string] $Name, [string] $Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "Comando '$Name' não encontrado. $Hint" }
}

function Assert-AzureContext {
    param([Parameter(Mandatory)] [string] $TenantId, [Parameter(Mandatory)] [string] $SubscriptionId)
    Assert-Command az 'Instale o Azure CLI: https://aka.ms/installazurecli'
    $acct = az account show -o json 2>$null | ConvertFrom-Json
    if (-not $acct) { throw "Sem sessão no Azure CLI. Rode: az login --tenant $TenantId" }
    if ($acct.tenantId -ne $TenantId) { throw "Tenant ativo ($($acct.tenantId)) difere do .env ($TenantId). Abortando." }
    if ($acct.id -ne $SubscriptionId) {
        throw "Subscription ativa ($($acct.id)) difere do .env ($SubscriptionId). Rode: az account set --subscription $SubscriptionId"
    }
    Write-Host "Azure: $($acct.user.name) | tenant $($acct.tenantId) | subscription $($acct.name)" -ForegroundColor DarkGray
}

function Get-OutputsPath {
    param([string] $Environment)
    return Join-Path (Split-Path $PSScriptRoot -Parent) "infra-outputs.$Environment.json"
}
