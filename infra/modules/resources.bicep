param location string
param prefix string
param environment string
param envShort string
param appServiceSku string
param m365DefaultDomain string
param usageLocation string
param timezone string
param logDailyCapGb int
param tags object

@description('Client ID do App Registration do portal. Vazio = login ainda não configurado.')
param entraClientId string = ''

@description('Fluxo de login do App Service: idtoken (GA, sem segredo) ou fic (Managed Identity como credencial federada — preview).')
@allowed(['idtoken', 'fic'])
param entraAuthFlow string = 'idtoken'

@description('IDs (separados por vírgula) de grupos que nunca podem ser usados em perfis — ex.: grupos dos papéis do portal.')
param protectedGroupIds string = ''

@description('Modo de licença: group (licenciamento por grupo, requer Entra ID P1) ou direct.')
@allowed(['group', 'direct'])
param licenseMode string = 'group'

@description('DRY_RUN: true = nenhuma alteração no Microsoft 365 (padrão seguro).')
param dryRun bool = true

@description('Máximo de contas criadas por dia (proteção).')
@minValue(1)
param provisioningDailyLimit int = 20

@description('Cria o agendador (Logic App) que executa o ciclo de vida de hora em hora.')
param enableScheduler bool = true

// Sufixo determinístico para nomes que precisam ser globais (Web App, Storage).
var suffix = take(uniqueString(subscription().id, resourceGroup().id, prefix, environment), 5)
var isFree = appServiceSku == 'F1'
var authEnabled = !empty(entraClientId)
var useFic = entraAuthFlow == 'fic'

// IDs de funções internas do Azure
var storageTableDataContributor = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var storageQueueDataContributor = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-${environment}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${prefix}-${environment}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: logDailyCapGb }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}-${environment}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    SamplingPercentage: 50
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: toLower('st${prefix}${envShort}${suffix}')
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // somente Entra ID / Managed Identity
    defaultToOAuthAuthentication: true
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource tables 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = [
  for t in ['solicitacoes', 'auditoria']: {
    parent: tableService
    name: t
  }
]

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource tasksQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'tarefas'
}

resource tableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, storageTableDataContributor)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributor)
  }
}

resource queueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, storageQueueDataContributor)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributor)
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'asp-${prefix}-${environment}'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: appServiceSku }
  properties: { reserved: true }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'app-${prefix}-${environment}-${suffix}'
  location: location
  tags: tags
  kind: 'app,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=* --no-server-header'
      alwaysOn: !isFree
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'ENVIRONMENT', value: environment }
        { name: 'DRY_RUN', value: dryRun ? 'true' : 'false' }
        { name: 'PROVISIONING_DAILY_LIMIT', value: string(provisioningDailyLimit) }
        { name: 'STORAGE_BACKEND', value: 'azure_table' }
        { name: 'AZURE_STORAGE_TABLE_ENDPOINT', value: storage.properties.primaryEndpoints.table }
        { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
        { name: 'AZURE_TENANT_ID', value: tenant().tenantId }
        { name: 'AUTH_MODE', value: 'easyauth' }
        { name: 'GRAPH_BACKEND', value: 'msgraph' }
        { name: 'PROTECTED_GROUP_IDS', value: protectedGroupIds }
        { name: 'LICENSE_MODE', value: licenseMode }
        { name: 'ENTRA_APP_CLIENT_ID', value: entraClientId }
        // Somente no fluxo 'fic': o login usa a Managed Identity como credencial federada
        { name: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID', value: useFic ? identity.properties.clientId : '' }
        { name: 'M365_DEFAULT_DOMAIN', value: m365DefaultDomain }
        { name: 'M365_DEFAULT_USAGE_LOCATION', value: usageLocation }
        { name: 'TIMEZONE', value: timezone }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
      ]
    }
  }
}

// App Service Authentication (Easy Auth) com Microsoft Entra ID — somente este tenant.
resource authSettings 'Microsoft.Web/sites/config@2023-12-01' = if (authEnabled) {
  parent: webApp
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true, runtimeVersion: '~1' }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: ['/health', '/health/ready']
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        // Sem clientSecretSettingName o App Service usa o fluxo de ID token (form_post), sem segredo.
        registration: union(
          {
            clientId: entraClientId
            openIdIssuer: '${az.environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
          },
          useFic ? { clientSecretSettingName: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID' } : {}
        )
        validation: {
          allowedAudiences: [entraClientId, 'api://${entraClientId}']
        }
      }
    }
    login: {
      tokenStore: { enabled: true }
      cookieExpiration: { convention: 'FixedTime', timeToExpiration: '08:00:00' }
      nonce: { validateNonce: true }
    }
    httpSettings: {
      requireHttps: true
      forwardProxy: { convention: 'NoProxy' }
    }
  }
}

// Desabilita autenticação básica (FTP e SCM); o deploy usa o token do Entra ID.
// Agendador do ciclo de vida (D-1 licença / D0 ativação): Logic App de consumo que chama
// o portal de hora em hora com a Managed Identity (token para api://<client-id>).
// O portal exige o App Role Provisionamento.Agendador, atribuído só a essa identidade.
resource scheduler 'Microsoft.Logic/workflows@2019-05-01' = if (authEnabled && enableScheduler) {
  name: 'logic-${prefix}-${environment}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: {
        de_hora_em_hora: {
          type: 'Recurrence'
          recurrence: { frequency: 'Hour', interval: 1 }
        }
      }
      actions: {
        executar_ciclo_de_vida: {
          type: 'Http'
          inputs: {
            method: 'POST'
            uri: 'https://${webApp.properties.defaultHostName}/interno/ciclo-de-vida'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: identity.id
              audience: 'api://${entraClientId}'
            }
          }
        }
      }
    }
  }
}

resource ftpPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: webApp
  name: 'ftp'
  properties: { allow: false }
}

resource scmPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: webApp
  name: 'scm'
  properties: { allow: false }
}

output authEnabled bool = authEnabled
output schedulerName string = (authEnabled && enableScheduler) ? scheduler.name : ''
output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output managedIdentityName string = identity.name
output managedIdentityClientId string = identity.properties.clientId
output managedIdentityPrincipalId string = identity.properties.principalId
output storageAccountName string = storage.name
output tableEndpoint string = storage.properties.primaryEndpoints.table
